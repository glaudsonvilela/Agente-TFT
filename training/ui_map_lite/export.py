"""Create an allowlisted inference graph from numeric arrays, WITHOUT importing PyTorch."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from .core import LAYERS, WIDTH, HEIGHT, ARCHITECTURE, require


def expected_shapes():
    shapes={}
    for i,(a,b,k,_,g) in enumerate(LAYERS):
        shapes[f'convs.{i}.weight']=(b,a//g,k,k);shapes[f'convs.{i}.bias']=(b,)
    shapes.update({'fc.weight':(96,1280),'fc.bias':(96,),'head.weight':(10,96),'head.bias':(10,)})
    return shapes


def export(weights: Path, target: Path):
    import onnx
    from onnx import helper as h, numpy_helper as nh, TensorProto as tp
    require(weights.is_file() and weights.stat().st_size<2*1024**2,'weight file budget')
    require(not target.exists(),'inference model already exists')
    shapes=expected_shapes()
    with np.load(weights,allow_pickle=False) as f:
        require(set(f.files)==set(shapes),'weight names differ from model contract')
        arrays={}
        for k,shape in shapes.items():
            a=f[k]
            require(a.shape==shape and a.dtype==np.float32 and np.isfinite(a).all(),'invalid weight: '+k)
            arrays[k]=a.copy()
    nodes=[];current='image'
    for i,(_,_,k,s,g) in enumerate(LAYERS):
        conv=f'conv{i}';out=f'relu{i}'
        nodes.append(h.make_node('Conv',[current,f'convs.{i}.weight',f'convs.{i}.bias'],[conv],
                                kernel_shape=[k,k],strides=[s,s],pads=[k//2]*4,group=g))
        nodes.append(h.make_node('Relu',[conv],[out]));current=out
    nodes += [h.make_node('AveragePool',[current],['pooled'],kernel_shape=[3,4],strides=[3,4]),
              h.make_node('Flatten',['pooled'],['flat'],axis=1),
              h.make_node('Gemm',['flat','fc.weight','fc.bias'],['fc'],transB=1),
              h.make_node('Relu',['fc'],['features']),
              h.make_node('Gemm',['features','head.weight','head.bias'],['logits'],transB=1),
              h.make_node('Sigmoid',['logits'],['regions'])]
    graph=h.make_graph(nodes,ARCHITECTURE,[h.make_tensor_value_info('image',tp.FLOAT,[1,3,HEIGHT,WIDTH])],
                       [h.make_tensor_value_info('regions',tp.FLOAT,[1,10])],
                       initializer=[nh.from_array(a,k) for k,a in arrays.items()])
    model=h.make_model(graph,opset_imports=[h.make_opsetid('',17)],producer_name='Agente-TFT UI-Map Lite U1')
    model.ir_version=10
    onnx.checker.check_model(model,full_check=True)
    with target.open('xb') as f:f.write(model.SerializeToString())
    return dict(parameters=sum(a.size for a in arrays.values()),
                operators=sorted(set(n.op_type for n in nodes)),model_bytes=target.stat().st_size,
                torch_imported=False,precision='FP32',quantized=False)
