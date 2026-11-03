"""TensorRT engine loader.

Kept inside the runtime so app-sjz/ does not import the training tree. Handles
both the TensorRT 8 binding API and the TensorRT 10 tensor API, so an engine
built with either one loads here.
"""

from collections import OrderedDict, namedtuple

import numpy as np
import torch

_NP_TO_TORCH = {
    np.dtype('float16'): torch.float16,
    np.dtype('float32'): torch.float32,
    np.dtype('int32'): torch.int32,
    np.dtype('int8'): torch.int8,
    np.dtype('bool'): torch.bool,
}


def _torch_dtype(np_dtype):
    return _NP_TO_TORCH.get(np.dtype(np_dtype), torch.float32)


def _tensor(engine, context, name):
    """(is_input, numpy dtype, shape) for one I/O tensor."""
    import tensorrt as trt
    if hasattr(engine, 'get_tensor_mode'):
        is_input = engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT
        dtype = trt.nptype(engine.get_tensor_dtype(name))
        shape = tuple(context.get_tensor_shape(name))
    else:
        i = engine.get_binding_index(name)
        is_input = engine.binding_is_input(i)
        dtype = trt.nptype(engine.get_binding_dtype(i))
        shape = tuple(context.get_binding_shape(i))
    return is_input, dtype, shape


def _profile_shape(engine, name):
    if hasattr(engine, 'get_tensor_profile_shape'):
        return tuple(engine.get_tensor_profile_shape(name, 0)[2])
    return tuple(engine.get_profile_shape(0, engine.get_binding_index(name))[2])


def _set_shape(context, engine, name, shape):
    if hasattr(context, 'set_input_shape'):
        context.set_input_shape(name, tuple(shape))
    else:
        context.set_binding_shape(engine.get_binding_index(name), tuple(shape))


def _tensor_shape(context, engine, name):
    if hasattr(context, 'get_tensor_shape'):
        return tuple(context.get_tensor_shape(name))
    return tuple(context.get_binding_shape(engine.get_binding_index(name)))


class Engine:
    """Runs one static-shape engine. The input buffer is whatever tensor is passed in."""

    def __init__(self, weights, device='cuda'):
        import tensorrt as trt
        self.device = torch.device(device)
        logger = trt.Logger(trt.Logger.WARNING)
        with open(weights, 'rb') as f, trt.Runtime(logger) as runtime:
            engine = runtime.deserialize_cuda_engine(f.read())
        if engine is None:
            raise RuntimeError('failed to deserialize {}'.format(weights))
        context = engine.create_execution_context()

        Binding = namedtuple('Binding', ('name', 'shape', 'data', 'ptr'))
        if hasattr(engine, 'num_io_tensors'):
            names = [engine.get_tensor_name(i) for i in range(engine.num_io_tensors)]
        else:
            names = [engine.get_binding_name(i) for i in range(engine.num_bindings)]

        bindings, outputs = OrderedDict(), []
        for name in names:
            is_input, dtype, shape = _tensor(engine, context, name)
            if is_input and -1 in shape:
                shape = _profile_shape(engine, name)
                _set_shape(context, engine, name, shape)
            if not is_input:
                outputs.append(name)
            buf = torch.empty(shape, dtype=_torch_dtype(dtype), device=self.device)
            bindings[name] = Binding(name, shape, buf, int(buf.data_ptr()))

        self.engine = engine
        self.context = context
        self.bindings = bindings
        self.outputs = outputs
        self.addrs = OrderedDict((n, b.ptr) for n, b in bindings.items())
        self.input = next(n for n in bindings if n not in outputs)
        self._static_set = False
        self._input_ptr = None

    def __call__(self, im):
        """Enqueue the engine on torch's current stream, without syncing.

        The runtime keeps its buffers alive between calls, so the input
        address only changes when the caller hands over a different tensor.
        The single D2H of the surviving rows later on the same stream is
        the sync point; a full synchronize here would just stall the
        pipeline while the NMS and the pick could already be enqueued.
        """
        expected = self.bindings[self.input].shape
        if tuple(im.shape) != expected:
            raise RuntimeError('engine expects {}, got {}'.format(expected, tuple(im.shape)))
        want = self.bindings[self.input].data.dtype
        if im.dtype != want:
            raise RuntimeError('engine input {} wants {}, got {}'.format(
                self.input, want, im.dtype))
        if hasattr(self.context, 'set_tensor_address'):
            # TRT 8.5+/10/11 tensor API: addresses persist on the context,
            # so rebind only when the caller's tensor actually moved.
            ptr = int(im.data_ptr())
            if not self._static_set:
                self._input_ptr = ptr
                self.addrs[self.input] = ptr
                for name, p in self.addrs.items():
                    self.context.set_tensor_address(name, p)
                self._static_set = True
            elif ptr != self._input_ptr:
                self._input_ptr = ptr
                self.addrs[self.input] = ptr
                self.context.set_tensor_address(self.input, ptr)
            self.context.execute_async_v3(torch.cuda.current_stream().cuda_stream)
        else:
            # TRT 8.x binding API: pass the address list on every call.
            self.addrs[self.input] = int(im.data_ptr())
            self.context.execute_v2(list(self.addrs.values()))
        out = [self.bindings[name].data for name in self.outputs]
        return out[0] if len(out) == 1 else out
