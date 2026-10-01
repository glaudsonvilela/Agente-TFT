//! Bounded photometric comparison and connected foreground, not a unit classifier.
use agente_tft_capture_core::FrameEnvelope;
use serde::Serialize;
use crate::profile::{rgb,Rect};

#[derive(Debug, Clone, Serialize)]
pub struct Appearance {
    pub offset: [i16;3],
    pub residual_mae: f32,
    pub changed_fraction: f32,
    pub correlation: f32,
    pub reference_spread: f32,
}
#[derive(Debug, Clone, Serialize)]
pub struct Component { pub rect: Rect, pub pixels: usize }

pub fn pixels(frame:&FrameEnvelope,r:Rect)->Vec<[u8;3]> {
    (r.y..r.y+r.height).flat_map(|y|(r.x..r.x+r.width).map(move |x|rgb(frame,x,y))).collect()
}
/// Median additive offsets preserve spatial residuals. Large offsets are rejected
/// by the caller; correlation is shape similarity, never calibrated confidence.
pub fn compare(a:&[[u8;3]],b:&[[u8;3]],threshold:u8)->Result<(Appearance,Vec<bool>),String> {
    if a.is_empty() || a.len()!=b.len() || a.len()>131072 {
        return Err("invalid photometric pixel budget".into());
    }
    let n=a.len();let mut offset=[0i16;3];
    let mut sum_a=[0.0;3];let mut sum_b=[0.0;3];
    for c in 0..3 {
        let mut delta:Vec<_>=a.iter().zip(b).map(|(x,y)|i16::from(y[c])-i16::from(x[c])).collect();
        delta.sort_unstable();offset[c]=delta[n/2];
        sum_a[c]=a.iter().map(|p|f64::from(p[c])).sum::<f64>()/n as f64;
        sum_b[c]=b.iter().map(|p|f64::from(p[c])).sum::<f64>()/n as f64;
    }
    let (mut residual,mut aa,mut bb,mut ab)=(0u64,0.0f64,0.0f64,0.0f64);
    let mut mask=Vec::with_capacity(n);
    for (x,y) in a.iter().zip(b) {
        let mut changed=false;
        for c in 0..3 {
            let d=(i16::from(y[c])-i16::from(x[c])-offset[c]).unsigned_abs();
            residual+=u64::from(d);changed|=d>u16::from(threshold);
            let u=f64::from(x[c])-sum_a[c];let v=f64::from(y[c])-sum_b[c];
            aa+=u*u;bb+=v*v;ab+=u*v;
        }
        mask.push(changed);
    }
    let correlation=if aa>1e-9 && bb>1e-9 {(ab/(aa*bb).sqrt()).clamp(-1.0,1.0)}else{-1.0};
    Ok((Appearance{offset,residual_mae:residual as f32/(n*3) as f32,
        changed_fraction:mask.iter().filter(|v|**v).count() as f32/n as f32,
        correlation:correlation as f32,reference_spread:(aa/(n*3) as f64).sqrt() as f32},mask))
}
/// Eight-connected components on the bounded crop. Every component, including
/// noise, consumes the component budget; failure never returns a partial list.
pub fn components(mask:&[bool],r:Rect,max_components:usize)->Result<Vec<Component>,String> {
    let w=r.width as usize;let h=r.height as usize;
    if w==0 || h==0 || w.checked_mul(h)!=Some(mask.len()) || mask.len()>131072 || max_components==0 {
        return Err("invalid foreground mask".into());
    }
    let mut seen=vec![false;mask.len()];let mut out=Vec::new();
    for start in 0..mask.len() {
        if !mask[start] || seen[start] {continue;}
        if out.len()>=max_components {return Err("foreground component budget exceeded".into());}
        seen[start]=true;let mut stack=vec![start];let mut count=0usize;
        let (mut x0,mut x1,mut y0,mut y1)=(w,0,h,0);
        while let Some(i)=stack.pop() {
            let x=i%w;let y=i/w;count+=1;x0=x0.min(x);x1=x1.max(x);y0=y0.min(y);y1=y1.max(y);
            for yy in y.saturating_sub(1)..=(y+1).min(h-1) {
                for xx in x.saturating_sub(1)..=(x+1).min(w-1) {
                    let j=yy*w+xx;
                    if mask[j] && !seen[j] {seen[j]=true;stack.push(j);}
                }
            }
        }
        out.push(Component{rect:Rect{x:r.x+x0 as u32,y:r.y+y0 as u32,
            width:(x1-x0+1) as u32,height:(y1-y0+1) as u32},pixels:count});
    }
    Ok(out)
}
