# import for cache
import os
import tempfile
import shutil
import hashlib
import sysconfig
import sys
# import for just-in-time compilation
import distutils
import setuptools.command.build_ext
import setuptools
# triton
import libtriton
# frameworks
import tensorflow as tf

extra_ops = tf.load_op_library('/home/philippe/development/triton/python/build/lib.linux-x86_64-3.6/libextra_tf_ops.so')


def make_bindings(src, out, grid):
  return libtriton.make_tensorflow_src(src, out, grid)

def make_cache_path(src):
  md5 = hashlib.sha1(src.encode())
  hexhash = md5.hexdigest()
  home = os.path.expanduser('~')
  cacheroot = os.path.join(home, '.triton', 'cache')
  cachepath = os.path.join(cacheroot, str(hexhash))
  if not os.path.exists(cachepath):
    os.makedirs(cachepath)
  return cachepath

def write_bindings(src, root):
  cpp = os.path.join(root, 'tensorflow.cpp')
  suffix = sysconfig.get_config_var('EXT_SUFFIX')
  so = os.path.join(root, 'tensorflow{suffix}'.format(suffix=suffix))
  recompile = False
  # recompile if .so does not exist
  if not os.path.exists(cpp) or not os.path.exists(so):
    recompile = True
  # recompile if cpp was modified after .so
  elif max(cpp, so, key=os.path.getctime) == cpp:
    recompile = True
  # write cpp file
  if recompile:
    with open(cpp, 'w+') as handle:
      handle.writelines(src)
  # return path of cpp file
  return (cpp, so)
  
def build(src, path):
  # include directories
  triton_include_dirs = ['/home/philippe/development/triton/include']
  tensorflow_include_dirs = [tf.sysconfig.get_include()]
  cuda_include_dirs = ['/usr/local/cuda-10.1/targets/x86_64-linux/include/']
  include_dirs = triton_include_dirs + tensorflow_include_dirs + cuda_include_dirs
  # library directories
  triton_library_dirs = [os.path.realpath(os.path.join(libtriton.__file__, os.path.pardir))]
  tensorflow_library_dirs = [tf.sysconfig.get_lib()]
  library_dirs = triton_library_dirs + tensorflow_library_dirs
  # libraries
  libraries = ['tensorflow_framework', 'triton']
  # extra arguments
  extra_compile_args = []
  extra_link_args = []
  # dependences
  depends = [os.path.realpath(libtriton.__file__)]
  # create extension module
  ext = setuptools.Extension(
      name = 'tensorflow',
      language = 'c++',
      sources = [src],
      include_dirs = include_dirs,
      extra_compile_args = extra_compile_args,
      extra_link_args = extra_link_args,
      library_dirs = library_dirs,
      libraries = libraries,
      depends = depends
  )
  # build extension module
  args = ['build_ext']
  tmp = tempfile.mkdtemp()
  args.append('--build-temp=' + tmp)
  args.append('--build-lib=' + path)
  args.append('-q')
  args = dict(
      name = 'tensorflow',
      ext_modules = [ext],
      script_args = args,
  ) 
  setuptools.setup(**args)
  shutil.rmtree(tmp)

def _cvt_to_def_str(obj):
  if isinstance(obj, bool):
    return str(int(obj))
  if isinstance(obj, tf.DType):
    return {tf.int8: 'char',
            tf.int16: 'short',
            tf.int32: 'int',
            tf.int64: 'long',
            tf.float16: 'half',
            tf.float32: 'float',
            tf.float64: 'double'}[obj]
  return str(obj)

class op:

  def _make_tensorflow_op(self, src, outputs, options):
    src, name = make_bindings(src, outputs, options)
    cache_path = make_cache_path(src)
    cpp, so = write_bindings(src, cache_path)
    build(cpp, cache_path)
    result = tf.load_op_library(so)
    return result.__dict__[name]

  def __init__(self, src, outputs):
    self.fw_ops = dict()
    self.src = src
    self.outputs = outputs
    pass
  
  def D(self, name):
    pass
  
  def __call__(self, *args, **kwargs):
    # recompilation key
    key = zip(kwargs.keys(), kwargs.values())
    # create a new op when non-iterable defines are different
    if key not in self.fw_ops:
      # code generation options
      defines = []
      for k, v in kwargs.items():
        try:
          values = list(map(_cvt_to_def_str, v))
        except TypeError:
          values = [_cvt_to_def_str(v)]
        defines.append((k, values))
      opt = libtriton.options_space()
      opt.defines = defines
      opt.num_warps = [1, 2, 4, 8]
      # register framework op
      id = libtriton.register_fn(self.src, opt)
      self.fw_ops[key] = (self._make_tensorflow_op(self.src, self.outputs, opt), id)
    # retrieve framework op
    op, id = self.fw_ops[key] 
    libtriton.register_grid(id, args[-1])
    op_args = args[:-1]
    return op(*op_args, id=id)


def make_tensorflow_op(src, outputs, grids):
  src, name = make_bindings(src, outputs, grids)
  cache_path = make_cache_path(src)
  cpp, so = write_bindings(src, cache_path)
  build(cpp, cache_path)
  result = tf.load_op_library(so)
  return result.__dict__[name]

def empty(shapes):
  return extra_ops.alloc_empty(tf.stack(shapes))
