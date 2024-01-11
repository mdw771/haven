from unittest import mock

from bluesky_queueserver_api import BPlan
from qtpy import QtCore

from firefly.plans.line_scan import LineScanDisplay

from ophyd.sim import make_fake_device
import pytest
from haven.instrument import motor


# fake motor copied from test_motor_menu.py, not sure this is right
@pytest.fixture
def fake_motors(sim_registry):
    motor_names = ["motorA_m2"]
    motors = []
    for name in motor_names:
        this_motor = make_fake_device(motor.HavenMotor)(name=name, labels={"motors"})
        sim_registry.register(this_motor)
        motors.append(this_motor)
    return motors


def test_line_scan_plan_queued(ffapp, qtbot, sim_registry):
    display = LineScanDisplay()
    display.ui.run_button.setEnabled(True)
    display.ui.num_motor_spin_box.setValue(2)
    display.update_regions()
    
    # set up a test motor 1
    display.regions[0].motor_box.combo_box.setCurrentText("test_motor1")
    display.regions[0].start_line_edit.setText("1")
    display.regions[0].stop_line_edit.setText("111")
    
    # set up a test motor 2
    display.regions[1].motor_box.combo_box.setCurrentText("test_motor2")
    display.regions[1].start_line_edit.setText("2")
    display.regions[1].stop_line_edit.setText("222")

    # set up scan num of points
    display.ui.scan_pts_spin_box.setValue(10)

    # set up detector list
    display.ui.detectors_list.selected_detectors = mock.MagicMock(
        return_value=["vortex_me4", "I0"]
    )
    

    expected_item = BPlan("scan", ["vortex_me4", "I0"], "test_motor1", 1, 111, "test_motor2" , 2, 222,  num=10)

    def check_item(item):
        from pprint import pprint

        pprint(item.to_dict())
        pprint(expected_item.to_dict())
        return item.to_dict() == expected_item.to_dict()

    # Click the run button and see if the plan is queued
    with qtbot.waitSignal(
        ffapp.queue_item_added, timeout=1000, check_params_cb=check_item
    ):
        qtbot.mouseClick(display.ui.run_button, QtCore.Qt.LeftButton)
