import os
from pathlib import Path
from unittest.mock import MagicMock
from types import SimpleNamespace
from collections import OrderedDict
from subprocess import Popen, TimeoutExpired, PIPE
import subprocess
import shutil
import time
from unittest import mock
import asyncio

import pytest
from qtpy import QtWidgets
import ophyd
from ophyd.sim import instantiate_fake_device, make_fake_device
from pydm.data_plugins import add_plugin


top_dir = Path(__file__).parent.parent.resolve()
ioc_dir = top_dir / "tests" / "iocs"
haven_dir = top_dir / "haven"
test_dir = top_dir / "tests"


import haven
from haven.simulated_ioc import simulated_ioc
from haven import registry, load_config
from haven.instrument.aps import ApsMachine
from haven.instrument.shutter import Shutter
from haven.instrument.camera import AravisDetector
from haven.instrument.fluorescence_detector import DxpDetectorBase
from firefly.application import FireflyApplication
from firefly.ophyd_plugin import OphydPlugin
from firefly.main_window import FireflyMainWindow
from run_engine import RunEngineStub


IOC_SCOPE = "function"
IOC_SCOPE = "session"


# Specify the configuration files to use for testing
os.environ["HAVEN_CONFIG_FILES"] = ",".join(
    [
        f"{test_dir/'iconfig_testing.toml'}",
        f"{haven_dir/'iconfig_default.toml'}",
    ]
)
load_config.cache_clear()


def pytest_configure(config):
    app = QtWidgets.QApplication.instance()
    assert app is None
    app = FireflyApplication()
    app = QtWidgets.QApplication.instance()
    assert isinstance(app, FireflyApplication)
    # # Create event loop for asyncio stuff
    # loop = asyncio.new_event_loop()
    # asyncio.set_event_loop(loop)


@pytest.fixture(scope="session")
def qapp_cls():
    return FireflyApplication


@pytest.fixture(scope=IOC_SCOPE)
def ioc_undulator(request):
    prefix = "ID255:"
    pvs = dict(energy=f"{prefix}Energy.VAL")
    return run_fake_ioc(
        module_name="haven.tests.ioc_undulator",
        name="Fake undulator IOC",
        prefix=prefix,
        pvs=pvs,
        pv_to_check=pvs["energy"],
        request=request,
    )


@pytest.fixture(scope=IOC_SCOPE)
def ioc_camera(request):
    prefix = "255idgigeA:"
    pvs = dict(
        cam_acquire=f"{prefix}cam1:Acquire",
        cam_acquire_busy=f"{prefix}cam1:AcquireBusy",
    )
    return run_fake_ioc(
        module_name="haven.tests.ioc_area_detector",
        name="Fake IOC for a simulated machine vision camera",
        prefix=prefix,
        pvs=pvs,
        pv_to_check=pvs["cam_acquire_busy"],
        request=request,
    )


@pytest.fixture(scope=IOC_SCOPE)
def ioc_area_detector(request):
    prefix = "255idSimDet:"
    pvs = dict(
        cam_acquire=f"{prefix}cam1:Acquire",
        cam_acquire_busy=f"{prefix}cam1:AcquireBusy",
    )
    return run_fake_ioc(
        module_name="haven.tests.ioc_area_detector",
        name="Fake IOC for a simulated area detector",
        prefix=prefix,
        pvs=pvs,
        pv_to_check=pvs["cam_acquire_busy"],
        request=request,
    )


@pytest.fixture(scope=IOC_SCOPE)
def ioc_bss(request):
    prefix = "255idc:bss:"
    pvs = dict(
        esaf_id=f"{prefix}esaf:id",
        esaf_cycle=f"{prefix}esaf:cycle",
        proposal_id=f"{prefix}proposal:id",
    )
    return run_fake_ioc(
        module_name="haven.tests.ioc_apsbss",
        name="Fake IOC for APS beamline scheduling system (BSS)",
        prefix=prefix,
        pvs=pvs,
        pv_to_check=pvs["esaf_cycle"],
        request=request,
    )


def run_fake_ioc(
    module_name,
    prefix: str,
    request,
    name="Fake IOC",
    pvs=None,
    pv_to_check: str = None,
):
    if pvs is None:
        pvs = {}
    pytest.importorskip("caproto.tests.conftest")
    from caproto.tests.conftest import run_example_ioc, poll_readiness

    process = run_example_ioc(
        module_name=module_name,
        request=request,
        pv_to_check=None,
        args=("--prefix", prefix, "--list-pvs", "-v"),
        very_verbose=False,
    )
    # Verify the IOC started
    if pv_to_check is not None:
        poll_timeout, poll_attempts = 1.0, 30
        poll_readiness(
            pv_to_check, timeout=poll_timeout, attempts=poll_attempts, process=process
        )
    return SimpleNamespace(
        process=process, prefix=prefix, name=name, pvs=pvs, type="caproto"
    )


@pytest.fixture(scope=IOC_SCOPE)
def ioc_scaler(request):
    prefix = "255idVME:scaler1"
    pvs = dict(calc=f"{prefix}_calc2.VAL")
    return run_fake_ioc(
        module_name="haven.tests.ioc_scaler",
        name="Fake scaler IOC",
        prefix=prefix,
        pvs=pvs,
        pv_to_check=pvs["calc"],
        request=request,
    )


@pytest.fixture(scope=IOC_SCOPE)
def ioc_ptc10(request):
    prefix = "255idptc10:"
    pvs = dict(
        pid1_voltage=f"{prefix}5A:output",
        pid1_voltage_rbv=f"{prefix}5A:output_RBV",
        tc1_temperature=f"{prefix}2A:temperature",
    )
    return run_fake_ioc(
        module_name="haven.tests.ioc_ptc10",
        name="Fake PTC10 temperature controller IOC",
        prefix=prefix,
        pvs=pvs,
        pv_to_check=pvs["tc1_temperature"],
        request=request,
    )


@pytest.fixture(scope="session")
def pydm_ophyd_plugin():
    return add_plugin(OphydPlugin)


@pytest.fixture()
def ffapp(pydm_ophyd_plugin):
    # Get an instance of the application
    app = FireflyApplication.instance()
    if app is None:
        app = FireflyApplication()
        app._dummy_main_window = FireflyMainWindow()
    # Set up the actions and other boildplate stuff
    app.setup_window_actions()
    app.setup_runengine_actions()
    assert isinstance(app, FireflyApplication)
    try:
        yield app
    finally:
        if hasattr(app, "_queue_thread"):
            app._queue_thread.quit()
        app.quit()
        del app


@pytest.fixture(scope=IOC_SCOPE)
def ioc_motor(request):
    prefix = "255idVME:"
    pvs = dict(m1=f"{prefix}m1", m2=f"{prefix}m2", m3=f"{prefix}m3", m4=f"{prefix}m4")
    return run_fake_ioc(
        module_name="haven.tests.ioc_motor",
        name="Fake motor IOC",
        prefix=prefix,
        pvs=pvs,
        pv_to_check=pvs["m1"],
        request=request,
    )


@pytest.fixture(scope=IOC_SCOPE)
def ioc_preamp(request):
    prefix = "255idc:"
    pvs = dict(
        preamp1_sens_num=f"{prefix}SR01:sens_num",
        preamp2_sens_num=f"{prefix}SR02:sens_num",
        preamp3_sens_num=f"{prefix}SR03:sens_num",
        preamp4_sens_num=f"{prefix}SR04:sens_num",
        preamp1_sens_unit=f"{prefix}SR01:sens_unit",
        preamp2_sens_unit=f"{prefix}SR02:sens_unit",
        preamp3_sens_unit=f"{prefix}SR03:sens_unit",
        preamp4_sens_unit=f"{prefix}SR04:sens_unit",
        preamp1_offset_num=f"{prefix}SR01:offset_num",
        preamp2_offset_num=f"{prefix}SR02:offset_num",
        preamp3_offset_num=f"{prefix}SR03:offset_num",
        preamp4_offset_num=f"{prefix}SR04:offset_num",
        preamp1_offset_unit=f"{prefix}SR01:offset_unit",
        preamp2_offset_unit=f"{prefix}SR02:offset_unit",
        preamp3_offset_unit=f"{prefix}SR03:offset_unit",
        preamp4_offset_unit=f"{prefix}SR04:offset_unit",
    )
    return run_fake_ioc(
        module_name="haven.tests.ioc_preamp",
        name="Fake preamp IOC",
        prefix=prefix,
        pvs=pvs,
        pv_to_check=pvs["preamp1_sens_num"],
        request=request,
    )


@pytest.fixture(scope=IOC_SCOPE)
def ioc_simple(request):
    prefix = "simple:"
    pvs = dict(
        A=f"{prefix}A",
        B=f"{prefix}B",
        C=f"{prefix}C",
    )
    pv_to_check = pvs["A"]
    return run_fake_ioc(
        module_name="haven.tests.ioc_simple",
        name="Fake simple IOC",
        prefix=prefix,
        pvs=pvs,
        pv_to_check=pv_to_check,
        request=request,
    )


@pytest.fixture(scope=IOC_SCOPE)
def ioc_mono(request):
    prefix = "255idMono:"
    pvs = dict(
        bragg=f"{prefix}ACS:m3",
        energy=f"{prefix}Energy",
        id_tracking=f"{prefix}ID_tracking",
        id_offset=f"{prefix}ID_offset",
    )
    return run_fake_ioc(
        module_name="haven.tests.ioc_mono",
        name="Fake mono IOC",
        prefix=prefix,
        pvs=pvs,
        pv_to_check=pvs["energy"],
        request=request,
    )


@pytest.fixture(scope=IOC_SCOPE)
def ioc_dxp(request):
    prefix = "255idDXP:"
    pvs = dict(acquiring=f"{prefix}Acquiring")
    return run_fake_ioc(
        module_name="haven.tests.ioc_dxp",
        name="Fake DXP-based detector IOC",
        prefix=prefix,
        pvs=pvs,
        pv_to_check=pvs["acquiring"],
        request=request,
    )


@pytest.fixture()
def sim_registry(monkeypatch):
    # mock out Ophyd connections so devices can be created
    modules = [
        haven.instrument.aps,
        haven.instrument.fluorescence_detector,
        haven.instrument.monochromator,
        haven.instrument.ion_chamber,
        haven.instrument.motor,
    ]
    for mod in modules:
        monkeypatch.setattr(mod, "await_for_connection", mock.AsyncMock())
    monkeypatch.setattr(
        haven.instrument.ion_chamber, "caget", mock.AsyncMock(return_value="I0")
    )
    # Clean the registry so we can restore it later
    components = registry.components
    registry.clear()
    # Run the test
    yield registry
    # Restore the previous registry components
    registry.components = components


# Simulated devices
@pytest.fixture()
def sim_aps(sim_registry):
    aps = instantiate_fake_device(ApsMachine, name="APS")
    sim_registry.register(aps)
    yield aps


@pytest.fixture()
def sim_shutters(sim_registry):
    FakeShutter = make_fake_device(Shutter)
    kw = dict(
        prefix="_prefix",
        open_pv="_prefix",
        close_pv="_prefix2",
        state_pv="_prefix2",
        labels={"shutters"},
    )
    shutters = [
        FakeShutter(name="Shutter A", **kw),
        FakeShutter(name="Shutter C", **kw),
    ]
    # Registry with the simulated registry
    for shutter in shutters:
        sim_registry.register(shutter)
    yield shutters


@pytest.fixture()
def sim_camera(sim_registry):
    FakeCamera = make_fake_device(AravisDetector)
    camera = FakeCamera(name="s255id-gige-A", labels={"cameras", "area_detectors"})
    camera.pva.pv_name._readback = "255idSimDet:Pva1:Image"
    # Registry with the simulated registry
    sim_registry.register(camera)
    yield camera


qs_status = {
    "msg": "RE Manager v0.0.18",
    "items_in_queue": 0,
    "items_in_history": 0,
    "running_item_uid": None,
    "manager_state": "idle",
    "queue_stop_pending": False,
    "worker_environment_exists": False,
    "worker_environment_state": "closed",
    "worker_background_tasks": 0,
    "re_state": None,
    "pause_pending": False,
    "run_list_uid": "4f2d48cc-980d-4472-b62b-6686caeb3833",
    "plan_queue_uid": "2b99ccd8-f69b-4a44-82d0-947d32c5d0a2",
    "plan_history_uid": "9af8e898-0f00-4e7a-8d97-0964c8d43f47",
    "devices_existing_uid": "51d8b88d-7457-42c4-b67f-097b168be96d",
    "plans_existing_uid": "65f11f60-0049-46f5-9eb3-9f1589c4a6dd",
    "devices_allowed_uid": "a5ddff29-917c-462e-ba66-399777d2442a",
    "plans_allowed_uid": "d1e907cd-cb92-4d68-baab-fe195754827e",
    "plan_queue_mode": {"loop": False},
    "task_results_uid": "159e1820-32be-4e01-ab03-e3478d12d288",
    "lock_info_uid": "c7fe6f73-91fc-457d-8db0-dfcecb2f2aba",
    "lock": {"environment": False, "queue": False},
}


@pytest.fixture()
def queue_app(ffapp):
    queue_api = MagicMock()
    queue_api.status.return_value = qs_status
    queue_api.queue_start.return_value = {"success": True}
    ffapp.setup_window_actions()
    ffapp.setup_runengine_actions()
    ffapp.prepare_queue_client(api=queue_api, start_thread=False)

    try:
        yield ffapp
    finally:
        # print(self._queue_thread)
        print("Exiting")
        ffapp._queue_thread.quit()
        ffapp._queue_thread.wait(5)


@pytest.fixture()
def sim_vortex(sim_registry):
    FakeDXP = make_fake_device(DxpDetectorBase)
    vortex = FakeDXP(name="vortex_me4", labels={"xrf_detectors", "detectors"})
    sim_registry.register(vortex)
    yield vortex


@pytest.fixture()
def RE(event_loop):
    return RunEngineStub(call_returns_result=True)
