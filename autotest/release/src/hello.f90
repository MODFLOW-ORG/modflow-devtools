! Print the kind of a default real and, given an expected kind as the first
! argument, fail when they differ. The version line is updated by
! scripts/version.py through release.toml.
program hello
  implicit none
  character(len=*), parameter :: VERSION = '0.1.0.dev0 01/01/2026'
  character(len=16) :: arg
  real :: x
  integer :: expected
  print '(a)', 'hello ' // VERSION
  print '(a,i0)', 'real kind ', kind(x)
  if (command_argument_count() > 0) then
    call get_command_argument(1, arg)
    read (arg, *) expected
    if (expected /= kind(x)) error stop 'unexpected real kind'
  end if
end program hello
