//! Documented WGC + D3D11 only. Selection uses public desktop metadata, never game memory.
use crate::{bad, packet, preview_rgb_from_bgra, rgb_from_bgra, Args, Result};
use serde::Serialize;
use serde_json::json;
use std::{io::BufRead, sync::{Arc, atomic::{AtomicBool, Ordering}, mpsc}, time::{Duration, Instant}};
use windows::{
    core::{factory, Interface, IInspectable, BOOL, PCWSTR},
    Foundation::TypedEventHandler,
    Graphics::{Capture::{Direct3D11CaptureFramePool, GraphicsCaptureItem, GraphicsCaptureSession},
               DirectX::{DirectXPixelFormat, Direct3D11::IDirect3DDevice}},
    Win32::{Foundation::{HWND, LPARAM, HMODULE, RECT},
        Graphics::{Gdi::*, Direct3D::*, Direct3D11::*, Dxgi::{IDXGIDevice, Common::*}},
        System::{WinRT::{RoInitialize, RO_INIT_MULTITHREADED,
            Direct3D11::{CreateDirect3D11DeviceFromDXGIDevice, IDirect3DDxgiInterfaceAccess},
            Graphics::Capture::IGraphicsCaptureItemInterop}, Performance::QueryPerformanceCounter},
        UI::{WindowsAndMessaging::*, HiDpi::*}},
};

#[derive(Clone, Serialize)]
pub struct Target {
    kind: String, id: String, label: String, device: String, adapter: String,
    bounds: [i32;4], primary: bool, pid: u32, dpi: u32, candidate_tft: bool,
}
fn wide(buf: &[u16]) -> String { String::from_utf16_lossy(&buf[..buf.iter().position(|v| *v==0).unwrap_or(buf.len())]) }
unsafe fn adapter_name(device: &str) -> String {
    for index in 0..32 {
        let mut d=DISPLAY_DEVICEW::default();d.cb=std::mem::size_of::<DISPLAY_DEVICEW>() as u32;
        if !EnumDisplayDevicesW(None,index,&mut d,0).as_bool() {break;}
        if wide(&d.DeviceName)==device {return wide(&d.DeviceString);}
    }
    String::new()
}
unsafe extern "system" fn monitor_cb(m: HMONITOR, _: HDC, _: *mut RECT, data: LPARAM) -> BOOL {
    let items=&mut *(data.0 as *mut Vec<Target>);
    let mut info=MONITORINFOEXW::default();info.monitorInfo.cbSize=std::mem::size_of::<MONITORINFOEXW>() as u32;
    if GetMonitorInfoW(m, (&mut info as *mut MONITORINFOEXW).cast()).as_bool() {
        let rect=info.monitorInfo.rcMonitor;let device=wide(&info.szDevice);
        let mut d=DISPLAY_DEVICEW::default();d.cb=std::mem::size_of::<DISPLAY_DEVICEW>() as u32;
        let label=if EnumDisplayDevicesW(PCWSTR(info.szDevice.as_ptr()),0,&mut d,0).as_bool() {wide(&d.DeviceString)} else {device.clone()};
        items.push(Target {kind:"monitor".into(),id:format!("{:x}",m.0 as usize),label,
            adapter:adapter_name(&device),device,bounds:[rect.left,rect.top,rect.right,rect.bottom],
            primary:info.monitorInfo.dwFlags&1!=0,pid:0,dpi:0,candidate_tft:false});
    }
    BOOL(1)
}
unsafe extern "system" fn window_cb(w: HWND, data: LPARAM) -> BOOL {
    if !IsWindowVisible(w).as_bool() || IsIconic(w).as_bool() {return BOOL(1);}
    let length=GetWindowTextLengthW(w);
    if length<=0 || length>1024 {return BOOL(1);}
    let mut text=vec![0;length as usize+1];GetWindowTextW(w,&mut text);
    let title=wide(&text);let mut r=RECT::default();
    if GetWindowRect(w,&mut r).is_err() || r.right<=r.left || r.bottom<=r.top {return BOOL(1);}
    let mut pid=0;GetWindowThreadProcessId(w,Some(&mut pid));
    let lower=title.to_lowercase();let hint=lower.contains("teamfight") || lower.contains("league of legends") || lower=="tft";
    let items=&mut *(data.0 as *mut Vec<Target>);
    items.push(Target {kind:"window".into(),id:format!("{:x}",w.0 as usize),label:title,
        device:String::new(),adapter:String::new(),bounds:[r.left,r.top,r.right,r.bottom],
        primary:false,pid,dpi:GetDpiForWindow(w),candidate_tft:hint});
    BOOL(1)
}
pub fn list() -> Result<Vec<Target>> {
    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        let mut items=Vec::<Target>::new();
        EnumDisplayMonitors(None,None,Some(monitor_cb),LPARAM((&mut items as *mut Vec<Target>) as isize)).ok()?;
        EnumWindows(Some(window_cb),LPARAM((&mut items as *mut Vec<Target>) as isize))?;
        Ok(items)
    }
}
fn qpc() -> Result<i64> { let mut n=0;unsafe {QueryPerformanceCounter(&mut n)?;} Ok(n) }

pub fn stream(args: &Args) -> Result<()> {
    unsafe {
        RoInitialize(RO_INIT_MULTITHREADED)?;
        if !GraphicsCaptureSession::IsSupported()? {return Err(bad("Windows.Graphics.Capture unsupported; no fallback"));}
        let target=list()?.into_iter().find(|t|t.kind==args.kind && t.id==args.id)
            .ok_or_else(||bad("selected target unavailable; select again"))?;
        let handle=usize::from_str_radix(&args.id,16)?;
        let interop:IGraphicsCaptureItemInterop=factory::<GraphicsCaptureItem,IGraphicsCaptureItemInterop>()?;
        let item:GraphicsCaptureItem=if args.kind=="monitor" {interop.CreateForMonitor(HMONITOR(handle as *mut _))?}
            else {interop.CreateForWindow(HWND(handle as *mut _))?};
        let mut device=None;let mut context=None;
        let mut device_kind="hardware";
        let flags=D3D11_CREATE_DEVICE_BGRA_SUPPORT;
        if D3D11CreateDevice(None,D3D_DRIVER_TYPE_HARDWARE,HMODULE::default(),flags,None,D3D11_SDK_VERSION,
                Some(&mut device),None,Some(&mut context)).is_err() {
            device_kind="warp";
            D3D11CreateDevice(None,D3D_DRIVER_TYPE_WARP,HMODULE::default(),flags,None,D3D11_SDK_VERSION,
                Some(&mut device),None,Some(&mut context))?;
        }
        let device=device.ok_or_else(||bad("D3D11 device absent"))?;
        let context=context.ok_or_else(||bad("D3D11 context absent"))?;
        let dxgi:IDXGIDevice=device.cast()?;
        let runtime_device:IDirect3DDevice=CreateDirect3D11DeviceFromDXGIDevice(&dxgi)?.cast()?;
        let format=DirectXPixelFormat::B8G8R8A8UIntNormalized;
        let mut size=item.Size()?;
        let pool=Direct3D11CaptureFramePool::CreateFreeThreaded(&runtime_device,format,2,size)?;
        let session=pool.CreateCaptureSession(&item)?;
        // Default OS capture border is not disabled or hidden.
        let stop=Arc::new(AtomicBool::new(false));
        let stop_input=stop.clone();
        std::thread::spawn(move || {
            let mut line=String::new();let _=std::io::stdin().lock().read_line(&mut line);
            stop_input.store(true,Ordering::Relaxed);
        });
        let closed=Arc::new(AtomicBool::new(false));let c=closed.clone();
        let close_token=item.Closed(&TypedEventHandler::<GraphicsCaptureItem,IInspectable>::new(move |_,_|{
            c.store(true,Ordering::Relaxed);Ok(())
        }))?;
        let (tx,rx)=mpsc::sync_channel(1);
        let token=pool.FrameArrived(&TypedEventHandler::<Direct3D11CaptureFramePool,IInspectable>::new(move |_,_|{
            let _=tx.try_send(());Ok(())
        }))?;
        let mut frequency=0;windows::Win32::System::Performance::QueryPerformanceFrequency(&mut frequency)?;
        packet(&json!({"type":"ready","bytes":0,"backend":"own_rust_wgc_d3d11_v1",
            "target":target,"device_kind":device_kind,"qpc_frequency":frequency,
            "pixel_format":"RGB8","capture_border_disabled":false,
            "preview_mode":if args.preview_hz.is_some() {"native_scaled_to_viewport_separate_from_analysis_v2"} else {"analysis_frames"},
            "preview_limit":[args.preview_width,args.preview_height],
            "color_policy":"BGRA8_SDR_contract_HDR_not_certified","cursor_policy":"OS_default",
            "screen_capture_active":true,"input_automation":false}), &[])?;
        session.StartCapture()?;
        let start=Instant::now();let mut last_analysis=None;let mut last_preview=None;
        let mut frame_id=0u64;let mut analysis_frames=0u64;let mut preview_frames=0u64;let mut seen=0u64;
        let mut rate_skipped=0u64;let mut size_changes=0u64;
        let mut staging:Option<ID3D11Texture2D>=None;let mut staging_dims=(0,0);
        let mut last_frame_at=start;
        let mut previous_write_ms=0.0;
        while !stop.load(Ordering::Relaxed) && start.elapsed().as_secs_f64()<args.seconds {
            if closed.load(Ordering::Relaxed) {return Err(bad("selected target closed; no switch to another source"));}
            if rx.recv_timeout(Duration::from_millis(100)).is_err() {
                if last_frame_at.elapsed()>Duration::from_secs(15) {return Err(bad("no frames for 15s; no hidden fallback"));}
                continue;
            }
            let frame=match pool.TryGetNextFrame() {Ok(f)=>f,Err(_)=>continue};
            let arrived_at=Instant::now();
            seen+=1;last_frame_at=arrived_at;
            let content=frame.ContentSize()?;
            if content.Width<=0 || content.Height<=0 {frame.Close()?;continue;}
            if content.Width!=size.Width || content.Height!=size.Height {
                frame.Close()?;size=content;
                pool.Recreate(&runtime_device,format,2,size)?;staging=None;size_changes+=1;
                packet(&json!({"type":"geometry_changed","bytes":0,"width":size.Width,"height":size.Height,
                    "segment":size_changes,"coordinates_reused":false}),&[])?;
                continue;
            }
            let analysis_due=last_analysis.is_none_or(|at:Instant|arrived_at.duration_since(at).as_secs_f64()>=1.0/args.hz);
            let preview_due=args.preview_hz.is_some_and(|hz|
                last_preview.is_none_or(|at:Instant|arrived_at.duration_since(at).as_secs_f64()>=1.0/hz));
            if !analysis_due && !preview_due {
                rate_skipped+=1;frame.Close()?;continue;
            }
            let capture_ns=frame.SystemRelativeTime()?.Duration.checked_mul(100).ok_or_else(||bad("time overflow"))?;
            let begin=qpc()?;
            let access:IDirect3DDxgiInterfaceAccess=frame.Surface()?.cast()?;
            let texture:ID3D11Texture2D=access.GetInterface()?;
            let mut desc=D3D11_TEXTURE2D_DESC::default();texture.GetDesc(&mut desc);
            if desc.Format!=DXGI_FORMAT_B8G8R8A8_UNORM {
                return Err(bad("unexpected capture pixel format"));
            }
            if content.Width as u32>desc.Width || content.Height as u32>desc.Height {
                frame.Close()?;size=content;
                pool.Recreate(&runtime_device,format,2,size)?;staging=None;size_changes+=1;
                packet(&json!({"type":"geometry_changed","bytes":0,"width":size.Width,"height":size.Height,
                    "segment":size_changes,"coordinates_reused":false,"reason":"texture_resize_lag"}),&[])?;
                continue;
            }
            if staging.is_none() || staging_dims!=(desc.Width,desc.Height) {
                let mut cpu_desc=desc;cpu_desc.Usage=D3D11_USAGE_STAGING;cpu_desc.BindFlags=0;
                cpu_desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ.0 as u32;cpu_desc.MiscFlags=0;
                device.CreateTexture2D(&cpu_desc,None,Some(&mut staging))?;
                staging_dims=(desc.Width,desc.Height);
            }
            let cpu=staging.as_ref().ok_or_else(||bad("missing staging texture"))?;
            context.CopyResource(cpu,&texture);
            let mut mapped=D3D11_MAPPED_SUBRESOURCE::default();
            context.Map(cpu,0,D3D11_MAP_READ,0,Some(&mut mapped))?;
            let after_map=qpc()?;
            let count=(mapped.RowPitch as usize).checked_mul(content.Height as usize).ok_or_else(||bad("mapped length overflow"))?;
            if mapped.pData.is_null() || count>256*1024*1024 {context.Unmap(cpu,0);return Err(bad("invalid mapped buffer"));}
            let source=std::slice::from_raw_parts(mapped.pData as *const u8,count);
            let preview=preview_due.then(||preview_rgb_from_bgra(source,
                content.Width as usize,content.Height as usize,mapped.RowPitch as usize,
                args.preview_width,args.preview_height));
            let analysis=analysis_due.then(||rgb_from_bgra(source,
                content.Width as usize,content.Height as usize,mapped.RowPitch as usize));
            context.Unmap(cpu,0);
            let preview=preview.transpose()?;let analysis=analysis.transpose()?;let after_rgb=qpc()?;
            frame.Close()?;
            let ticks_to_ms=|n:i64|n as f64*1000.0/frequency as f64;
            for (kind,width,height,rgb) in
                preview.map(|(w,h,rgb)|("preview",w,h,rgb)).into_iter()
                .chain(analysis.map(|rgb|("frame",content.Width as usize,content.Height as usize,rgb))) {
                let outgoing=json!({"type":kind,"bytes":rgb.len(),"frame_id":frame_id,
                    "width":width,"height":height,"source_width":content.Width,"source_height":content.Height,
                    "stride_bytes":width*3,"capture_ns":capture_ns,"clock":"WGC_SystemRelativeTime_QPC_nanoseconds",
                    "qpc_acquired_ticks":begin,"qpc_sent_ticks":after_rgb,"qpc_frequency":frequency,"geometry_segment":size_changes,
                    "frames_received":seen,"rate_skipped":rate_skipped,"pixel_format":"RGB8",
                    "gpu_copy_and_map_ms":ticks_to_ms(after_map-begin),"bgra_rgb_ms":ticks_to_ms(after_rgb-after_map),
                    "previous_ipc_write_ms":previous_write_ms,"capture_space":args.kind,
                    "capture_age_before_ipc_ms":after_rgb as f64*1000.0/frequency as f64-capture_ns as f64/1e6});
                let write=Instant::now();packet(&outgoing,&rgb)?;previous_write_ms=write.elapsed().as_secs_f64()*1000.0;
                if kind=="preview" {preview_frames+=1;last_preview=Some(arrived_at);}
                else {analysis_frames+=1;last_analysis=Some(arrived_at);}
            }
            frame_id+=1;
        }
        session.Close()?;pool.RemoveFrameArrived(token)?;pool.Close()?;item.RemoveClosed(close_token)?;
        if analysis_frames==0 {return Err(bad("no captured analysis frame"));}
        packet(&json!({"type":"end","bytes":0,"frames":analysis_frames,"preview_frames":preview_frames,"received":seen,
            "rate_skipped":rate_skipped,"size_changes":size_changes,"stop_requested":stop.load(Ordering::Relaxed),
            "last_ipc_write_ms":previous_write_ms,"execution_complete":!closed.load(Ordering::Relaxed)}),&[])?;
        Ok(())
    }
}
