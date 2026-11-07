"""Stop the owned Unreal process group and wait for RPC/streaming port release."""
import os
import signal
import socket
import subprocess
import time


def ports_free():
    sockets=[]
    try:
        for port in (2000,2001,2002):
            sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            sockets.append(sock)
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            sock.bind(('127.0.0.1',port))
        return True
    except OSError:
        return False
    finally:
        for sock in sockets:sock.close()


def stop_process_group(server):
    # CarlaUE4.sh can exit before its Unreal child, so poll() is not sufficient.
    try:os.killpg(server.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    deadline=time.monotonic()+15
    while not ports_free() and time.monotonic()<deadline:time.sleep(.2)
    if not ports_free():
        try:os.killpg(server.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:raise RuntimeError('owned CARLA wrapper did not exit')
    deadline=time.monotonic()+5
    while not ports_free() and time.monotonic()<deadline:time.sleep(.1)
    if not ports_free():raise RuntimeError('CARLA ports still occupied after owned group cleanup')


def ensure_map(client,town):
    world=client.get_world()
    if world.get_map().name.split('/')[-1]!=town:
        world=client.load_world(town)
    if world.get_map().name.split('/')[-1]!=town:
        raise RuntimeError('CARLA returned an unexpected actual map')
    return world
