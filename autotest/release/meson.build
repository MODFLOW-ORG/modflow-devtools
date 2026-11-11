project(
  'hello',
  'fortran',
  version: '0.1.0.dev0',
  license: 'CC0',
  meson_version: '>= 1.7.0',
  default_options: [
    'b_vscrt=static_from_buildtype',
    'buildtype=release',
  ],
)

is_double = get_option('double')
fc = meson.get_compiler('fortran')
args = []
if is_double
  if fc.get_id() == 'gcc'
    args += ['-fdefault-real-8', '-fdefault-double-8']
  elif fc.get_id() == 'intel-llvm-cl' or fc.get_id() == 'intel-cl'
    args += ['/real-size:64', '/double-size:64']
  else
    args += ['-real-size', '64', '-double-size', '64']
  endif
endif
link_args = []
if fc.get_id() == 'intel-llvm' or fc.get_id() == 'intel'
  link_args += ['-static-intel']
elif fc.get_id() == 'gcc' and host_machine.system() == 'linux'
  link_args += ['-static-libgfortran', '-static-libgcc']
endif

name = is_double ? 'hellodbl' : 'hello'
exe = executable(
  name,
  'src/hello.f90',
  fortran_args: args,
  link_args: link_args,
  install: true,
)
test('kind', exe, args: [is_double ? '8' : '4'])
