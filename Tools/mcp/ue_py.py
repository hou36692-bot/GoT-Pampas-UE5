"""Run a Python file inside the open UE editor via PythonScriptPlugin remote execution.

Usage (Blender's python, isolated):
  python -I Tools/mcp/ue_py.py <script.py> [--eval]
The script runs with `unreal` available; print() output is returned.
Requires Project Settings > Plugins > Python > Enable Remote Execution (localhost only).
"""
import sys, time, pathlib

UE_PY = r'D:\UE\UE_5.8\Engine\Plugins\Experimental\PythonScriptPlugin\Content\Python'
sys.path.append(UE_PY)
import remote_execution as rx  # noqa: E402


def main():
    path = pathlib.Path(sys.argv[1]).resolve()
    cfg = rx.RemoteExecutionConfig()
    cfg.multicast_bind_address = '127.0.0.1'
    re_ = rx.RemoteExecution(cfg)
    re_.start()
    try:
        for _ in range(50):
            if re_.remote_nodes:
                break
            time.sleep(0.1)
        if not re_.remote_nodes:
            print('NO_UE_NODE'); sys.exit(2)
        re_.open_command_connection(re_.remote_nodes[0]['node_id'])
        cmd = f"exec(open(r'{path}', encoding='utf-8').read(), {{'__name__': '__ue_remote__', '__file__': r'{path}'}})"
        res = re_.run_command(cmd, unattended=True, exec_mode=rx.MODE_EXEC_STATEMENT)
        for o in res.get('output', []):
            sys.stdout.write(o.get('output', ''))
            if not o.get('output', '').endswith('\n'):
                sys.stdout.write('\n')
        if not res.get('success'):
            print('RESULT:', res.get('result')); sys.exit(1)
    finally:
        re_.stop()


if __name__ == '__main__':
    main()
