//! Experimental Windows-only resident Tesseract backend.
//! Not wired into production readers until CLI parity gates pass.
use std::{ffi::{CStr,CString,c_char,c_int,c_void},path::{Path,PathBuf}};

use agente_tft_capture_core::RoiFrame;
use agente_tft_image_preprocess::{preprocess_for_numeric_ocr,GrayImage};
use agente_tft_perception_hud::{parse_xp_current,HudField,HudOcrEngine,HudPreprocessConfig,HudReadError,RecognizedText};
use libloading::Library;

use crate::{numeric_gray,parse_tsv,TesseractConfig};

type ApiCreate=unsafe extern "C" fn()->*mut c_void;
type ApiDelete=unsafe extern "C" fn(*mut c_void);
type ApiEnd=unsafe extern "C" fn(*mut c_void);
type ApiClear=unsafe extern "C" fn(*mut c_void);
type ApiInit3=unsafe extern "C" fn(*mut c_void,*const c_char,*const c_char)->c_int;
type ApiSetVariable=unsafe extern "C" fn(*mut c_void,*const c_char,*const c_char)->c_int;
type ApiSetPsm=unsafe extern "C" fn(*mut c_void,c_int);
type ApiSetImage=unsafe extern "C" fn(*mut c_void,*const u8,c_int,c_int,c_int,c_int);
type ApiRecognize=unsafe extern "C" fn(*mut c_void,*mut c_void)->c_int;
type ApiGetTsv=unsafe extern "C" fn(*mut c_void,c_int)->*mut c_char;
type DeleteText=unsafe extern "C" fn(*const c_char);

pub struct ResidentTesseractOcr {
    // Keep the DLL loaded for the complete lifetime of all copied function pointers.
    _lib: Library,
    api:*mut c_void,
    delete:ApiDelete,
    end:ApiEnd,
    clear:ApiClear,
    set_variable:ApiSetVariable,
    set_psm:ApiSetPsm,
    set_image:ApiSetImage,
    recognize_api:ApiRecognize,
    get_tsv:ApiGetTsv,
    delete_text:DeleteText,
    config:TesseractConfig,
    numeric_gray:bool,
    dll_path:PathBuf,
    tessdata_path:PathBuf,
}

impl ResidentTesseractOcr {
    pub fn from_cli_path(binary:impl AsRef<Path>,language:impl Into<String>)->Result<Self,String>{
        let binary=binary.as_ref();
        let root=binary.parent().ok_or_else(||"tesseract binary has no parent directory".to_string())?;
        let dll=["libtesseract-5.dll","libtesseract.dll"].into_iter().map(|n|root.join(n))
            .find(|p|p.is_file()).ok_or_else(||format!("libtesseract DLL not found beside {}",binary.display()))?;
        let tessdata=root.join("tessdata");
        if !tessdata.is_dir(){return Err(format!("tessdata directory missing: {}",tessdata.display()))}
        Self::new(dll,tessdata,TesseractConfig{binary:binary.to_string_lossy().into_owned(),language:language.into()})
    }

    pub fn new(dll:impl AsRef<Path>,tessdata:impl AsRef<Path>,config:TesseractConfig)->Result<Self,String>{
        let dll=dll.as_ref().to_path_buf();
        let tessdata=tessdata.as_ref().to_path_buf();
        if !dll.is_file(){return Err(format!("resident OCR DLL missing: {}",dll.display()))}
        if !tessdata.is_dir(){return Err(format!("resident OCR tessdata missing: {}",tessdata.display()))}
        unsafe {
            let lib=Library::new(&dll).map_err(|e|format!("failed to load {}: {e}",dll.display()))?;
            let create:ApiCreate=*lib.get::<ApiCreate>(b"TessBaseAPICreate\0").map_err(|e|e.to_string())?;
            let delete:ApiDelete=*lib.get::<ApiDelete>(b"TessBaseAPIDelete\0").map_err(|e|e.to_string())?;
            let end:ApiEnd=*lib.get::<ApiEnd>(b"TessBaseAPIEnd\0").map_err(|e|e.to_string())?;
            let clear:ApiClear=*lib.get::<ApiClear>(b"TessBaseAPIClear\0").map_err(|e|e.to_string())?;
            let init3:ApiInit3=*lib.get::<ApiInit3>(b"TessBaseAPIInit3\0").map_err(|e|e.to_string())?;
            let set_variable:ApiSetVariable=*lib.get::<ApiSetVariable>(b"TessBaseAPISetVariable\0").map_err(|e|e.to_string())?;
            let set_psm:ApiSetPsm=*lib.get::<ApiSetPsm>(b"TessBaseAPISetPageSegMode\0").map_err(|e|e.to_string())?;
            let set_image:ApiSetImage=*lib.get::<ApiSetImage>(b"TessBaseAPISetImage\0").map_err(|e|e.to_string())?;
            let recognize_api:ApiRecognize=*lib.get::<ApiRecognize>(b"TessBaseAPIRecognize\0").map_err(|e|e.to_string())?;
            let get_tsv:ApiGetTsv=*lib.get::<ApiGetTsv>(b"TessBaseAPIGetTsvText\0").map_err(|e|e.to_string())?;
            let delete_text:DeleteText=*lib.get::<DeleteText>(b"TessDeleteText\0").map_err(|e|e.to_string())?;
            let api=create();
            if api.is_null(){return Err("TessBaseAPICreate returned null".into())}
            let data=CString::new(tessdata.to_string_lossy().as_bytes()).map_err(|_|"tessdata path contains NUL".to_string())?;
            let lang=CString::new(config.language.as_bytes()).map_err(|_|"language contains NUL".to_string())?;
            if init3(api,data.as_ptr(),lang.as_ptr())!=0{
                delete(api);return Err("TessBaseAPIInit3 failed".into())
            }
            Ok(Self{_lib:lib,api,delete,end,clear,set_variable,set_psm,set_image,recognize_api,get_tsv,delete_text,
                    config,numeric_gray:false,dll_path:dll,tessdata_path:tessdata})
        }
    }

    pub fn with_numeric_gray(mut self)->Self{self.numeric_gray=true;self}
    pub fn dll_path(&self)->&Path{&self.dll_path}
    pub fn tessdata_path(&self)->&Path{&self.tessdata_path}
    pub fn language(&self)->&str{&self.config.language}

    fn uses_gray(&self,field:HudField)->bool{
        self.numeric_gray && matches!(field,HudField::Gold|HudField::Level|HudField::Xp)
    }
    fn psm_for(&self,field:HudField)->c_int{
        if field==HudField::Stage || self.uses_gray(field){7}else{8}
    }
    fn whitelist_for(field:HudField)->&'static str{
        match field {
            HudField::Stage=>"0123456789-",
            HudField::Xp=>"0123456789/",
            HudField::Gold|HudField::Hp|HudField::Level=>"0123456789",
        }
    }
    fn accept_text(&self,field:HudField,text:&str)->bool{
        !self.uses_gray(field) || field!=HudField::Xp || (text.contains('/') && parse_xp_current(text).is_ok())
    }

    fn run_tsv(&mut self,field:HudField,image:&GrayImage)->Result<String,String>{
        image.validate().map_err(|e|format!("invalid grayscale image: {e}"))?;
        let key=CString::new("tessedit_char_whitelist").unwrap();
        let value=CString::new(Self::whitelist_for(field)).unwrap();
        unsafe {
            (self.clear)(self.api);
            if (self.set_variable)(self.api,key.as_ptr(),value.as_ptr())==0{
                return Err("TessBaseAPISetVariable failed".into())
            }
            (self.set_psm)(self.api,self.psm_for(field));
            (self.set_image)(self.api,image.pixels.as_ptr(),image.width as c_int,image.height as c_int,1,image.stride_bytes as c_int);
            if (self.recognize_api)(self.api,std::ptr::null_mut())!=0{
                return Err("TessBaseAPIRecognize failed".into())
            }
            let ptr=(self.get_tsv)(self.api,0);
            if ptr.is_null(){return Err("TessBaseAPIGetTsvText returned null".into())}
            let text=CStr::from_ptr(ptr).to_string_lossy().into_owned();
            (self.delete_text)(ptr);
            Ok(text)
        }
    }
}

impl HudOcrEngine for ResidentTesseractOcr {
    fn prepare_roi(&self,field:HudField,roi:&RoiFrame,config:HudPreprocessConfig)->Result<GrayImage,HudReadError>{
        if self.uses_gray(field){numeric_gray::prepare(field,roi,config)}
        else{preprocess_for_numeric_ocr(roi,config.upscale_factor,config.invert).map_err(|e|HudReadError::Preprocess(e.to_string()))}
    }
    fn recognize(&mut self,field:HudField,image:&GrayImage)->Result<Option<RecognizedText>,String>{
        let tsv=self.run_tsv(field,image)?;
        Ok(parse_tsv(&tsv)?.filter(|r|self.accept_text(field,&r.text)))
    }
}
impl Drop for ResidentTesseractOcr {
    fn drop(&mut self){unsafe{(self.end)(self.api);(self.delete)(self.api);}}
}
