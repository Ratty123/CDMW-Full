"""Crimson Desert Mod Workbench package."""

# Before anything imports numpy: OpenBLAS sizes its thread pool when it loads, and
# every entry point (the app, each worker mode, the MCP bridge, the tests' conftest)
# imports this package first. See cdmw/app/native_threads.py.
from cdmw.app.native_threads import limit_native_thread_pools as _limit_native_thread_pools

_limit_native_thread_pools()
