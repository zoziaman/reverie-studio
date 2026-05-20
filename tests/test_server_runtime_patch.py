from utils.server_manager import ServerManager, has_registered_processes, register_managed_process
from utils.server_runtime_patch import apply_server_runtime_patch


class _FakeProcess:
    def __init__(self, pid: int = 1234):
        self.pid = pid
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def stop(self):
        self._alive = False


def test_apply_server_runtime_patch_adds_stop_all_servers():
    apply_server_runtime_patch()
    manager = ServerManager()
    assert hasattr(manager, "stop_all_servers")


def test_stop_all_servers_cleans_registered_processes(monkeypatch):
    apply_server_runtime_patch()

    def _fake_terminate(process, _server_name):
        process.stop()
        return True

    monkeypatch.setattr("utils.server_runtime_patch._terminate_process", _fake_terminate)
    monkeypatch.setattr("utils.server_manager._terminate_process", _fake_terminate)

    manager = ServerManager()
    fake_process = _FakeProcess()
    register_managed_process("SD WebUI", fake_process)

    results = manager.stop_all_servers(["SD WebUI"])

    assert results["SD WebUI"] is True
    assert has_registered_processes("SD WebUI") is False
