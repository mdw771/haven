import os
from pathlib import Path
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
from ophyd import DynamicDeviceComponent as DDC, Kind
from ophyd.sim import (
    instantiate_fake_device,
    make_fake_device,
    fake_device_cache,
    FakeEpicsSignal,
)
from pydm.data_plugins import add_plugin


top_dir = Path(__file__).parent.parent.resolve()
ioc_dir = top_dir / "tests" / "iocs"
haven_dir = top_dir / "haven"
test_dir = top_dir / "tests"


import haven
from haven.simulated_ioc import simulated_ioc
from haven import load_config, registry
from haven._iconfig import beamline_connected as _beamline_connected
from haven.instrument.stage import AerotechFlyer, AerotechStage
from haven.instrument.aps import ApsMachine
from haven.instrument.shutter import Shutter
from haven.instrument.camera import AravisDetector
from haven.instrument.delay import EpicsSignalWithIO
from haven.instrument.dxp import DxpDetectorBase, add_mcas as add_dxp_mcas
from haven.instrument.ion_chamber import IonChamber
from haven.instrument.xspress import Xspress3Detector, add_mcas as add_xspress_mcas
from firefly.application import FireflyApplication
from firefly.ophyd_plugin import OphydPlugin
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


class FakeEpicsSignalWithIO(FakeEpicsSignal):
    # An EPICS signal that simply uses the DG-645 convention of
    # 'AO' being the setpoint and 'AI' being the read-back
    _metadata_keys = EpicsSignalWithIO._metadata_keys

    def __init__(self, prefix, **kwargs):
        super().__init__(f"{prefix}I", write_pv=f"{prefix}O", **kwargs)


fake_device_cache[EpicsSignalWithIO] = FakeEpicsSignalWithIO


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
    # Set up the actions and other boildplate stuff
    app.setup_window_actions()
    app.setup_runengine_actions()
    assert isinstance(app, FireflyApplication)
    yield app
    if hasattr(app, "_queue_thread"):
        app._queue_thread.quit()


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
        haven.instrument.fluorescence_detector,
        haven.instrument.monochromator,
        haven.instrument.ion_chamber,
        haven.instrument.motor,
        haven.instrument.device,
    ]
    for mod in modules:
        monkeypatch.setattr(mod, "await_for_connection", mock.AsyncMock())
    monkeypatch.setattr(
        haven.instrument.ion_chamber, "caget", mock.AsyncMock(return_value="I0")
    )
    # Clean the registry so we can restore it later
    objects_by_name = registry._objects_by_name
    objects_by_label = registry._objects_by_label
    registry.clear()
    # Run the test
    yield registry
    # Restore the previous registry components
    registry._objects_by_name = objects_by_name
    registry._objects_by_label = objects_by_label


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


class DxpVortex(DxpDetectorBase):
    mcas = DDC(
        add_dxp_mcas(range_=[0, 1, 2, 3]),
        kind=Kind.normal | Kind.hinted,
        default_read_attrs=[f"mca{i}" for i in [0, 1, 2, 3]],
        default_configuration_attrs=[f"mca{i}" for i in [0, 1, 2, 3]],
    )


@pytest.fixture()
def dxp(sim_registry):
    FakeDXP = make_fake_device(DxpVortex)
    vortex = FakeDXP(name="vortex_me4", labels={"xrf_detectors"})
    sim_registry.register(vortex)
    # vortex.net_cdf.dimensions.set([1477326, 1, 1])
    yield vortex


@pytest.fixture()
def sim_vortex(dxp):
    return dxp


class Xspress3Vortex(Xspress3Detector):
    mcas = DDC(
        add_xspress_mcas(range_=[0, 1, 2, 3]),
        kind=Kind.normal | Kind.hinted,
        default_read_attrs=[f"mca{i}" for i in [0, 1, 2, 3]],
        default_configuration_attrs=[f"mca{i}" for i in [0, 1, 2, 3]],
    )


@pytest.fixture()
def xspress(sim_registry):
    FakeXspress = make_fake_device(Xspress3Vortex)
    vortex = FakeXspress(name="vortex_me4", labels={"xrf_detectors"})
    sim_registry.register(vortex)
    yield vortex


@pytest.fixture()
def sim_ion_chamber(sim_registry):
    FakeIonChamber = make_fake_device(IonChamber)
    ion_chamber = FakeIonChamber(
        prefix="scaler_ioc", name="I00", labels={"ion_chambers"}, ch_num=2
    )
    sim_registry.register(ion_chamber)
    return ion_chamber


@pytest.fixture()
def I0(sim_registry):
    """A fake ion chamber named 'I0' on scaler channel 2."""
    FakeIonChamber = make_fake_device(IonChamber)
    ion_chamber = FakeIonChamber(
        prefix="scaler_ioc", name="I0", labels={"ion_chambers"}, ch_num=2
    )
    sim_registry.register(ion_chamber)
    return ion_chamber


@pytest.fixture()
def It(sim_registry):
    """A fake ion chamber named 'It' on scaler channel 3."""
    FakeIonChamber = make_fake_device(IonChamber)
    ion_chamber = FakeIonChamber(
        prefix="scaler_ioc", name="It", labels={"ion_chambers"}, ch_num=3
    )
    sim_registry.register(ion_chamber)
    return ion_chamber


@pytest.fixture()
def sim_aerotech():
    Stage = make_fake_device(
        AerotechStage,
    )
    stage = Stage(
        "255id",
        delay_prefix="255id:DG645",
        pv_horiz=":m1",
        pv_vert=":m2",
        name="aerotech",
    )
    return stage


@pytest.fixture()
def sim_aerotech_flyer(sim_aerotech):
    flyer = sim_aerotech.horiz
    flyer.user_setpoint._limits = (0, 1000)
    flyer.send_command = mock.MagicMock()
    # flyer.encoder_resolution.put(0.001)
    # flyer.acceleration.put(1)
    yield flyer


@pytest.fixture()
def RE(event_loop):
    return RunEngineStub(call_returns_result=True)


@pytest.fixture()
def beamline_connected():
    with _beamline_connected(True):
        yield
