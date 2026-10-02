"""One bounded L3 optimization; model selection uses validation, never the test result."""
import copy,json,time
import numpy as np
import torch
from .model import UIMapPath,loss_function,save_weights
from . import legacy
from uimap_lite_l2.common import require


def fit(renderer,validation,plan,out,initial_weights):
    torch.set_num_threads(plan['training_threads']);torch.manual_seed(plan['seed'])
    torch.use_deterministic_algorithms(True)
    from uimap_lite_l2.model import load_weights as load_l2
    model=UIMapPath();transfer=load_l2(initial_weights).state_dict()
    transfer['grid_x']=model.grid_x.clone();transfer['grid_y']=model.grid_y.clone()
    model.load_state_dict(transfer);save_weights(model,out/'initial-weights.npz')
    print('LITE3_PHASE=canonical_native_data',flush=True)
    started=time.perf_counter();cache=renderer.cache(plan['training_samples'],plan['seed']*100000)
    vx,vy,vv,_=validation.cache(plan['validation_samples'],plan['seed']*100000+10000)
    cache_seconds=time.perf_counter()-started
    rng=np.random.default_rng(plan['seed']);optimizer=torch.optim.Adam(model.parameters(),lr=.0015)
    def score():
        model.eval();total=[]
        with torch.inference_mode():
            for s in range(0,len(vx),12):
                x=torch.from_numpy(vx[s:s+12].astype(np.float32)/255)
                p,m=model.components(x)
                total.append(float(loss_function(p,m,torch.from_numpy(vy[s:s+12]),torch.from_numpy(vv[s:s+12]))))
        return float(np.mean(total))
    initial=score();best=initial;state=copy.deepcopy(model.state_dict());best_step=0;history=[]
    started=time.perf_counter()
    with (out/'training.jsonl').open('x') as log:
        for step in range(1,plan['training_steps']+1):
            ids=rng.integers(0,len(cache[0]),plan['batch_size'])
            x=torch.from_numpy(cache[0][ids].astype(np.float32)/255)
            y=torch.from_numpy(cache[1][ids]);v=torch.from_numpy(cache[2][ids])
            model.train();optimizer.zero_grad(set_to_none=True);p,m=model.components(x)
            loss=loss_function(p,m,y,v);require(torch.isfinite(loss).item(),'nonfinite loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);optimizer.step()
            if step%100==0 or step==plan['training_steps']:
                value=score();row=dict(step=step,train_loss=float(loss.detach()),validation_loss=value,
                                       elapsed_seconds=time.perf_counter()-started)
                history.append(row);log.write(json.dumps(row)+'\n');log.flush();print('LITE3_TRAIN='+json.dumps(row),flush=True)
                if value<best:best=value;state=copy.deepcopy(model.state_dict());best_step=step
    elapsed=time.perf_counter()-started;model.load_state_dict(state);model.eval();save_weights(model,out/'weights.npz')
    with np.load(out/'initial-weights.npz',allow_pickle=False) as initial_weights:
        delta=sum(float(abs(v.detach().numpy()-initial_weights[k]).sum()) for k,v in model.named_parameters())
    return model,dict(parameters=sum(p.numel() for p in model.parameters()),training_steps=plan['training_steps'],
        selected_step=best_step,initial_validation_loss=initial,best_validation_loss=best,
        canonical_cache_seconds=cache_seconds,training_seconds=elapsed,parameter_l1_delta=delta,
        model_trained=delta>0,history=history),vx[:16].astype(np.float32)/255
