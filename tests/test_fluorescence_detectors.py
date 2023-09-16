"""Tests for all the fluorescence detectors.

These tests are mostly parameterized to ensure that both DXP and
Xspress detectors share a common interface. A few of the tests are
specific to one device or another.

"""

import logging
from pathlib import Path
import asyncio
from unittest.mock import MagicMock
import time

import numpy as np
import pytest
from epics import caget
from ophyd import Kind, DynamicDeviceComponent as DDC, OphydObject
from bluesky import plans as bp

from haven.instrument.dxp import parse_xmap_buffer, load_dxp
from haven.instrument.xspress import load_xspress


DETECTORS = ['dxp', 'xspress']
# DETECTORS = ['dxp']


@pytest.fixture()
def vortex(request):
    """Parameterized fixture for creating a Vortex device with difference
    electronics support.

    """
    # Figure out which detector we're using
    det = request.getfixturevalue(request.param)
    yield det


def test_load_xspress(sim_registry, mocker):
    load_xspress(config=None)
    vortex = sim_registry.find(name="vortex_me4_xsp")
    assert vortex.mcas.component_names == ("mca0", "mca1", "mca2", "mca3")


def test_load_dxp(sim_registry):
    load_dxp(config=None)
    # See if the device was loaded
    vortex = sim_registry.find(name="vortex_me4")
    # Check that the MCA's are available
    assert hasattr(vortex.mcas, "mca0")
    assert hasattr(vortex.mcas, "mca1")
    assert hasattr(vortex.mcas, "mca2")
    assert hasattr(vortex.mcas, "mca3")
    # Check that MCA's have ROI's available
    assert hasattr(vortex.mcas.mca1, "rois")
    assert hasattr(vortex.mcas.mca1.rois, "roi0")
    # Check that bluesky hints were added
    assert hasattr(vortex.mcas.mca1.rois.roi0, "use")
    # assert vortex.mcas.mca1.rois.roi1.is_hinted.pvname == "vortex_me4:mca1_R1BH"


# @pytest.mark.parametrize("vortex", ["xspress"], indirect=True)
def test_acquire_frames_xspress(xspress):
    """Can we acquire a single frame using the dedicated signal."""
    vortex = xspress
    # Acquire a single frame
    assert vortex.acquire.get() == 0
    vortex.acquire_single.set(1).wait(timeout=3)
    # Check that the num of frames and the acquire button were set
    assert vortex.acquire.get() == 1
    assert vortex.cam.num_images.get() == 1
    assert vortex.acquire_single.get() == 1
    # Does it stop as well
    vortex.acquire_single.set(0).wait(timeout=3)
    assert vortex.acquire.get() == 0
    # Acquire multiple frames
    vortex.acquire_multiple.set(1).wait(timeout=3)
    # Check that the num of frames and the acquire button were set
    assert vortex.acquire.get() == 1
    assert vortex.cam.num_images.get() == 2000
    assert vortex.acquire_single.get() == 1


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
def test_roi_size(vortex, caplog):
    """Do the signals for max/size auto-update."""
    roi = vortex.mcas.mca0.rois.roi0
    # Check that we can set the lo_chan without error in the callback
    with caplog.at_level(logging.ERROR):
        roi.lo_chan.set(10).wait(timeout=3)
    for record in caplog.records:
        assert "Another set() call is still in progress" not in record.exc_text, record.exc_text
    # Update the size and check the maximum
    roi.size.set(7).wait(timeout=3)
    assert roi.hi_chan.get() == 17
    # Update the maximum and check the size
    roi.hi_chan.set(28).wait(timeout=3)
    assert roi.size.get() == 18
    # Update the minimum and check the size
    roi.lo_chan.set(25).wait(timeout=3)
    assert roi.size.get() == 3


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
def test_roi_size_concurrency(vortex, caplog):
    roi = vortex.mcas.mca0.rois.roi0
    # Set up the roi limits
    roi.lo_chan.set(12).wait(timeout=3)
    roi.size.set(13).wait(timeout=3)
    assert roi.hi_chan.get() == 25
    # Change two signals together
    statuses = [
        roi.lo_chan.set(3),
        roi.hi_chan.set(5),
    ]
    for st in statuses:
        st.wait(timeout=3)
    # Check that the signals were set correctly
    assert roi.lo_chan.get() == 3
    assert roi.hi_chan.get() == 5
    assert roi.size.get() == 2


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)        
def test_enable_some_rois(vortex):
    """Test that the correct ROIs are enabled/disabled."""
    print(vortex)
    statuses = vortex.enable_rois(rois=[2, 5], elements=[1, 3])
    # Give the IOC time to change the PVs
    for status in statuses:
        status.wait(timeout=3)
        # Check that at least one of the ROIs was changed
    roi = vortex.mcas.mca1.rois.roi2
    hinted = roi.use.get(use_monitor=False)
    assert hinted == 1


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)    
def test_enable_rois(vortex):
    """Test that the correct ROIs are enabled/disabled."""
    statuses = vortex.enable_rois()
    # Give the IOC time to change the PVs
    for status in statuses:
        status.wait(timeout=3)
        # Check that at least one of the ROIs was changed
    roi = vortex.mcas.mca1.rois.roi2
    hinted = roi.use.get(use_monitor=False)
    assert hinted == 1


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
def test_disable_some_rois(vortex):
    """Test that the correct ROIs are enabled/disabled."""
    statuses = vortex.enable_rois(rois=[2, 5], elements=[1, 3])
    # Give the IOC time to change the PVs
    for status in statuses:
        status.wait(timeout=3)
    # Check that at least one of the ROIs was changed
    roi = vortex.mcas.mca1.rois.roi2
    hinted = roi.use.get(use_monitor=False)
    assert hinted == 1
    statuses = vortex.disable_rois(rois=[2, 5], elements=[1, 3])
    # Give the IOC time to change the PVs
    for status in statuses:
        status.wait(timeout=3)
    # Check that at least one of the ROIs was changed
    roi = vortex.mcas.mca1.rois.roi2
    hinted = roi.use.get(use_monitor=False)
    assert hinted == 0


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
def test_disable_rois(vortex):
    """Test that the correct ROIs are enabled/disabled."""
    statuses = vortex.enable_rois()
    # Give the IOC time to change the PVs
    for status in statuses:
        status.wait(timeout=3)

    statuses = vortex.disable_rois()
    # Give the IOC time to change the PVs
    for status in statuses:
        status.wait(timeout=3)
        # Check that at least one of the ROIs was changed
    roi = vortex.mcas.mca1.rois.roi2
    hinted = roi.use.get(use_monitor=False)
    assert hinted == 0


@pytest.mark.xfail
def test_with_plan(vortex):
    assert False, "Write test"


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
def test_stage_signal_names(vortex):
    """Check that we can set the name of the detector ROIs dynamically."""
    dev = vortex.mcas.mca1.rois.roi1
    dev.label.put("Ni-Ka")
    # Ensure the name isn't changed yet
    assert "Ni-Ka" not in dev.name
    assert "Ni_Ka" not in dev.name
    orig_name = dev.name
    dev.stage()
    try:
        result = dev.read()
    except Exception:
        raise
    else:
        assert "Ni-Ka" not in dev.name  # Make sure it gets sanitized
        assert "Ni_Ka" in dev.name
    finally:
        dev.unstage()
    # Name gets reset when unstaged
    assert dev.name == orig_name
    # Check acquired data uses dynamic names
    for res in result.keys():
        assert "Ni_Ka" in res


@pytest.mark.parametrize("vortex", DETECTORS, indirect=True)
def test_read_and_config_attrs(vortex):
    vortex.mcas.mca0.read_attrs
    expected_read_attrs = [
        "mcas",
        "dead_time_average",
        "dead_time_min",
        "dead_time_max",
    ]
    if hasattr(vortex, 'cam'):
        expected_read_attrs.append("cam")
    # Add attrs for each MCA and ROI.
    for mca in range(vortex.num_elements):
        expected_read_attrs.extend([
            f"mcas.mca{mca}",
            f"mcas.mca{mca}.rois",
            f"mcas.mca{mca}.spectrum",
            f"mcas.mca{mca}.total_count",
            # f"mcas.mca{mca}.input_count_rate",
            # f"mcas.mca{mca}.output_count_rate",
            f"mcas.mca{mca}.dead_time_percent",
            f"mcas.mca{mca}.dead_time_factor",
            # f"mcas.mca{mca}.background",
        ])
        for roi in range(vortex.num_rois):
            expected_read_attrs.extend([
                f"mcas.mca{mca}.rois.roi{roi}",
                f"mcas.mca{mca}.rois.roi{roi}.count",
                f"mcas.mca{mca}.rois.roi{roi}.net_count",
            ])
    assert sorted(vortex.read_attrs) == sorted(expected_read_attrs)


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
def test_use_signal(vortex):
    """Check that the ``.use`` ROI signal properly mangles the label.

    It uses label mangling instead of any underlying PVs because
    different detector types don't have this feature or use it in an
    undesirable way.

    """
    roi = vortex.mcas.mca0.rois.roi1
    roi.label.sim_put("Fe-55")
    # Enable the ROI and see if the name is updated
    roi.use.set(False).wait(timeout=3)
    assert roi.label.get() == "~Fe-55"
    # Disable the ROI and see if it goes back
    roi.use.set(True).wait(timeout=3)
    assert roi.label.get() == "Fe-55"
    # Set the label manually and see if the use signal changes
    roi.label.set("~Fe-55").wait(timeout=3)
    assert not bool(roi.use.get())

    
@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
def test_stage_signal_hinted(vortex):
    dev = vortex.mcas.mca0.rois.roi1
    # Check that ROI is not hinted by default
    assert dev.name not in vortex.hints
    # Enable the ROI by setting it's kind PV to "hinted"
    dev.use.set(True).wait(timeout=3)
    # Ensure signals are not hinted before being staged
    assert dev.net_count.name not in vortex.hints["fields"]
    try:
        dev.stage()
    except Exception:
        raise
    else:
        assert dev.net_count.name in vortex.hints["fields"]
        assert (
            vortex.mcas.mca1.rois.roi0.net_count.name
            not in vortex.hints["fields"]
        )
    finally:
        dev.unstage()
    # Did it restore kinds properly when unstaging
    assert dev.net_count.name not in vortex.hints["fields"]
    assert (
        vortex.mcas.mca1.rois.roi0.net_count.name not in vortex.hints["fields"]
    )


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
@pytest.mark.xfail
def test_kickoff_dxp(vortex):
    vortex = vortex
    vortex.write_path = "M:\\tmp\\"
    vortex.read_path = "/net/s20data/sector20/tmp/"
    [
        s.wait(timeout=3)
        for s in [
            vortex.acquiring.set(0),
            vortex.collect_mode.set("MCA Spectrum"),
            vortex.erase_start.set(0),
            vortex.pixel_advance_mode.set("Sync"),
        ]
    ]
    # Ensure that the vortex is in its normal operating state
    assert vortex.collect_mode.get(use_monitor=False) == "MCA Spectrum"
    # Check that the kickoff status ended properly
    status = vortex.kickoff()
    assert not status.done
    vortex.acquiring.set(1)
    status.wait(timeout=3)
    assert status.done
    assert status.success
    # Check that the right signals were set during  kick off
    assert vortex.collect_mode.get(use_monitor=False) == "MCA Mapping"
    assert vortex.erase_start.get(use_monitor=False) == 1
    assert vortex.pixel_advance_mode.get(use_monitor=False) == "Gate"
    # Check that the netCDF writer was setup properly
    assert vortex.net_cdf.enable.get(use_monitor=False) == "Enable"
    assert vortex.net_cdf.file_path.get(use_monitor=False) == "M:\\tmp\\"
    assert vortex.net_cdf.file_name.get(use_monitor=False) == "fly_scan_temp.nc"
    assert vortex.net_cdf.capture.get(use_monitor=False) == 1


def test_dxp_acquire(dxp):
    """Check that the DXP acquire mimics that of the area detector base."""
    assert dxp.stop_all.get(use_monitor=False) == 0
    assert dxp.erase_start.get(use_monitor=False) == 0
    dxp.acquire.set(1).wait(timeout=3)
    assert dxp.stop_all.get(use_monitor=False) == 0
    assert dxp.erase_start.get(use_monitor=False) == 1
    dxp.acquire.set(0).wait(timeout=3)
    assert dxp.stop_all.get(use_monitor=False) == 1
    assert dxp.erase_start.get(use_monitor=False) == 1

    # Now test the reverse behavior
    dxp.acquire.set(0).wait(timeout=3)
    assert dxp.acquire.get(use_monitor=False) == 0
    dxp.acquiring.set(1).wait(timeout=3)
    assert dxp.acquire.get(use_monitor=False) == 1
    dxp.acquiring.set(0).wait(timeout=3)
    assert dxp.acquire.get(use_monitor=False) == 0


def test_complete_dxp(dxp):
    """Check the behavior of the DXP electornic's fly-scan complete call."""
    vortex = dxp
    vortex.write_path = "M:\\tmp\\"
    vortex.read_path = "/net/s20data/sector20/tmp/"
    vortex.acquire._readback = 1
    status = vortex.complete()
    time.sleep(0.01)
    assert vortex.stop_all.get(use_monitor=False) == 1
    assert not status.done
    vortex.acquiring.set(0)
    status.wait(timeout=3)
    assert status.done


def test_kickoff_xspress(xspress):
    """Check the behavior of the Xspress3 electornic's fly-scan complete call."""
    vortex = xspress
    vortex.acquire.sim_put(0)
    status = vortex.kickoff()
    assert not status.done
    # Set the acquire signal to true to test that signals got set
    vortex.detector_state.sim_put(vortex.detector_states.ACQUIRE)
    status.wait(timeout=3)
    assert status.done
    assert vortex.cam.trigger_mode.get() == vortex.trigger_modes.TTL_VETO_ONLY
    assert vortex.acquire.get() == vortex.acquire_states.ACQUIRE
    

def test_complete_xspress(xspress):
    """Check the behavior of the Xspress3 electornic's fly-scan complete call."""
    vortex = xspress
    vortex.acquire.sim_put(1)
    status = vortex.complete()
    time.sleep(0.01)
    assert vortex.acquire.get(use_monitor=False) == 0
    assert status.done


def test_collect_xspress(xspress):
    """Check the Xspress3 collects data during fly-scanning."""
    vortex = xspress
    # Kick off the detector
    status = vortex.kickoff()
    vortex.detector_state.sim_put(vortex.detector_states.ACQUIRE)
    status.wait(timeout=3)
    # Set some data so we have something to report
    roi = vortex.mcas.mca0.rois.roi0
    roi.net_count.sim_put(281)
    assert vortex._fly_data[roi.net_count][0][1] == 281
    roi = vortex.mcas.mca1.rois.roi0
    roi.net_count.sim_put(217)
    assert vortex._fly_data[roi.net_count][0][1] == 217
    # Make sure the element sums aren't collected here, but calculated later
    assert vortex.roi_sums.roi0 not in vortex._fly_data.keys()
    # Get data and check its structure
    data = list(vortex.collect())
    datum = data[0]
    assert datum["data"][vortex.mcas.mca0.rois.roi0.net_count.name] == 281
    assert datum["data"][vortex.mcas.mca1.rois.roi0.net_count.name] == 217


def test_describe_collect_xspress(xspress):
    vortex = xspress
    # Force all the ROI counts to update
    for mca_num, mca in enumerate(vortex.mca_records()):
        for roi_num in range(vortex.num_rois):
            roi = vortex.get_roi(mca_num, roi_num)
            roi.count.get()
    desc = vortex.describe_collect()
    # Perform some spot-checks for descriptions
    assert vortex.name in desc.keys()
    sub_desc = desc[vortex.name]
    assert vortex.mcas.mca0.total_count.name in sub_desc.keys()
    assert vortex.mcas.mca0.dead_time_percent.name in sub_desc.keys()
    assert vortex.mcas.mca0.spectrum.name in sub_desc.keys()
    assert vortex.mcas.mca0.rois.roi0.net_count.name in sub_desc.keys()
    assert vortex.mcas.mca0.rois.roi0.count.name in sub_desc.keys()


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
@pytest.mark.xfail
def test_parse_xmap_buffer(vortex):
    """The output for fly-scanning with the DXP-based readout electronics
    is a raw uint16 buffer that must be parsed by the ophyd device
    according to section 5.3.3 of
    https://cars9.uchicago.edu/software/epics/XMAP_User_Manual.pdf

    """
    fp = Path(__file__)
    buff = np.loadtxt(fp.parent / "dxp_3px_4elem_Fe55.txt")
    data = parse_xmap_buffer(buff)
    assert isinstance(data, dict)
    assert data["num_pixels"] == 3
    assert len(data["pixels"]) == 3


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
def test_roi_counts(vortex):
    """Check that the ROIs determine their counts from the spectrum."""
    mca = vortex.mcas.mca0
    roi = mca.rois.roi0
    # Create a fake spectrum
    spectrum_size = 4096
    spectrum = np.zeros(spectrum_size)
    spectrum[512:1024] = 1
    mca.spectrum.sim_put(spectrum)
    # Does the total count only pull from the given ROI limits
    roi.lo_chan.set(800).wait(timeout=3)
    roi.size.set(100).wait(timeout=3)
    # Does the total count add together the spectrum?
    count = roi.count.get()
    assert type(count) is int
    assert count == 101
    # Try setting bounds outside the spectrum size
    roi.lo_chan.set(-100).wait(timeout=3)
    roi.hi_chan.set(spectrum_size + 100).wait(timeout=3)
    assert roi.count.get() == 512
    


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
def test_roi_calcs(vortex):
    # Check that the ROI calc signals exist
    assert isinstance(vortex.roi_sums.roi0, OphydObject)
    # Set some fake ROI values
    print(vortex.mcas.mca0.rois.roi0.net_count)
    vortex.mcas.mca0.rois.roi0.net_count.sim_put(5)
    assert vortex.roi_sums.roi0.get() == 5


@pytest.mark.parametrize('vortex', DETECTORS, indirect=True)
def test_mca_calcs(vortex):
    # Check that the ROI calc signals exist
    assert isinstance(vortex.mcas.mca0.total_count, OphydObject)
    # Does it sum together the total counts?
    spectrum = np.random.randint(2**16, size=(vortex.num_rois))
    mca = vortex.mcas.mca0
    mca.spectrum.sim_put(spectrum)
    assert mca.total_count.get(use_monitor=False) == np.sum(spectrum)

@pytest.mark.parametrize("vortex", ["xspress"], indirect=True)
def test_dead_time_calc(vortex):
    assert vortex.dead_time_average.get(use_monitor=False) == 0
    assert vortex.dead_time_max.get(use_monitor=False) == 0
    assert vortex.dead_time_min.get(use_monitor=False) == 0
    # Set the per-element dead-times
    dead_times = [3, 4, 5, 6]
    for mca, dt in zip(vortex.mca_records(), dead_times):
        mca.dead_time_percent.sim_put(dt)
    # Check that the stats get updated
    assert vortex.dead_time_min.get(use_monitor=False) == 3
    assert vortex.dead_time_max.get(use_monitor=False) == 6
    assert vortex.dead_time_average.get(use_monitor=False) == 4.5
