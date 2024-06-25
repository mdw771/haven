import asyncio
import logging

from qasync import asyncSlot

from firefly import display
from firefly.plans.util import is_valid_value, time_converter

log = logging.getLogger()


class RegionBase:
    def __init__(self, line_label: str = ""):
        self.line_label = line_label
        self.setup_ui()

    def setup_ui(self):
        raise NotImplementedError


class RegionsDisplay(display.FireflyDisplay):
    """Contains variable number of plan parameter regions in a table.

    Should be subclassed to produce a usable display.

    Expects the subclass to have the following attributes:

    ui.regions_layout
      The vertical layout to receive the paramter regions.
    ui.num_motor_spin_box
      A spin box widget for how many regions to show.
    ui.run_button
      A button widget that will queue the plan.
    Region
      The object representing the region view to put into the layout.
    queue_plan
      A method that emits to `queue_item_submitted` signal with a plan
      item.

    """

    default_num_regions = 1
    Region = RegionBase

    def customize_ui(self):
        # Remove the default layout from .ui file
        self.clearLayout(self.ui.region_template_layout)

        # Disable the line edits in spin box (use up/down buttons instead)
        self.ui.num_motor_spin_box.lineEdit().setReadOnly(True)

        # Set up the mechanism for changing region number
        self.regions = []
        self.ui.num_motor_spin_box.valueChanged.connect(self.update_regions_slot)
        self.reset_default_regions()

        self.ui.run_button.setEnabled(True)  # for testing
        self.ui.run_button.clicked.connect(self.queue_plan)

    @asyncSlot(object)
    async def update_devices(self, registry):
        """Set available components in the motor boxes."""
        await super().update_devices(registry)
        await self.update_component_selector_devices(registry)
        if hasattr(self.ui, "detectors_list"):
            await self.ui.detectors_list.update_devices(registry)

    async def update_component_selector_devices(self, registry):
        """Update the devices for all the component selectors"""
        selectors = [region.motor_box for region in self.regions]
        aws = [box.update_devices(registry) for box in selectors]
        await asyncio.gather(*aws)

    def clearLayout(self, layout):
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

    def reset_default_regions(self):
        self.ui.num_motor_spin_box.setValue(self.default_num_regions)

    def add_regions(self, num: int = 1):
        """Add *num* regions to the list of scan parameters.

        Returns
        =======
        new_regions
          The newly created region objects.

        """
        new_regions = []
        for i in range(num):
            region = self.Region(len(self.regions))
            self.ui.regions_layout.addLayout(region.layout)
            # Save it to the list
            self.regions.append(region)
            new_regions.append(region)
        # Finish setting up the new regions
        return new_regions

    def remove_regions(self, num=1):
        for i in range(num):
            layout = self.regions[-1].layout
            # iterate/wait, and delete all widgets in the layout in the end
            while len(layout.count()) > 0:
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.regions.pop()

    @asyncSlot(int)
    async def update_regions_slot(self, new_region_num):
        return await self.update_regions(new_region_num)

    async def update_regions(self, new_region_num: int):
        """Adjust regions from the scan params layout to reach
        *new_region_num*.

        """
        old_region_num = len(self.regions)
        diff_region_num = new_region_num - old_region_num
        new_regions = []
        if diff_region_num < 0:
            self.remove_regions(abs(diff_region_num))
        elif diff_region_num > 0:
            new_regions = self.add_regions(diff_region_num)
        # Setup the component selector devices with existing device definitions
        if len(new_regions) > 0:
            aws = [
                region.motor_box.update_devices(self.registry) for region in new_regions
            ]
            await asyncio.gather(*aws)

    def update_total_time(self):
        # get default detector time
        detectors = self.ui.detectors_list.selected_detectors()
        detectors = [self.registry[name] for name in detectors]
        detectors = [det for det in detectors if hasattr(det, "default_time_signal")]

        # to prevent detector list is empty
        try:
            detector_time = max([det.default_time_signal.get() for det in detectors])
        except ValueError:
            detector_time = float("nan")

        # get scan num points to calculate total time
        total_time_per_scan = self.time_calculate_method(detector_time)

        # calculate time for each scan
        hrs, mins, secs = time_converter(total_time_per_scan)
        self.ui.label_hour_scan.setText(str(hrs))
        self.ui.label_min_scan.setText(str(mins))
        self.ui.label_sec_scan.setText(str(secs))

        # calculate time for entire plan
        num_scan_repeat = self.ui.spinBox_repeat_scan_num.value()
        total_time = num_scan_repeat * total_time_per_scan
        hrs_total, mins_total, secs_total = time_converter(total_time)

        self.ui.label_hour_total.setText(str(hrs_total))
        self.ui.label_min_total.setText(str(mins_total))
        self.ui.label_sec_total.setText(str(secs_total))

    def time_calculate_method(self, detector_time):
        num_points = self.ui.scan_pts_spin_box.value()
        total_time_per_scan = detector_time * num_points
        return total_time_per_scan

    def get_scan_parameters(self):
        # Get scan parameters from widgets
        detectors = self.ui.detectors_list.selected_detectors()
        num_points = self.ui.scan_pts_spin_box.value()
        repeat_scan_num = int(self.ui.spinBox_repeat_scan_num.value())

        # Get paramters from each rows of line regions:
        motor_lst, start_lst, stop_lst = [], [], []
        for region_i in self.regions:
            motor_lst.append(region_i.motor_box.current_component().name)
            start_lst.append(float(region_i.start_line_edit.text()))
            stop_lst.append(float(region_i.stop_line_edit.text()))

        motor_args = [
            values
            for motor_i in zip(motor_lst, start_lst, stop_lst)
            for values in motor_i
        ]

        # Get meta data info
        md = {
            "sample": self.ui.lineEdit_sample.text(),
            "purpose": self.ui.lineEdit_purpose.text(),
            "notes": self.ui.textEdit_notes.toPlainText(),
        }
        # Only include metadata that isn't an empty string
        md = {key: val for key, val in md.items() if is_valid_value(val)}

        return detectors, num_points, motor_args, repeat_scan_num, md
