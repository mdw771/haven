"""Holds ion chamber detector descriptions and assignments to EPICS PVs."""

from typing import Sequence
import logging
import math

from ophyd import (
    Device,
    status,
    EpicsMotor,
    EpicsSignal,
    PVPositionerPC,
    PseudoPositioner,
    PseudoSingle,
    Component as Cpt,
    FormattedComponent as FCpt,
    Kind,
)
from ophyd.pseudopos import pseudo_position_argument, real_position_argument
from ophyd.status import DeviceStatus
from apstools.devices import SRS570_PreAmplifier

from .instrument_registry import registry
from .scaler_triggered import ScalerTriggered
from .._iconfig import load_config

# from ..signal import Signal, SignalRO
from ophyd import EpicsSignal as Signal, EpicsSignalRO as SignalRO
from .. import exceptions


log = logging.getLogger(__name__)


__all__ = ["IonChamber"]


iconfig = load_config()

ioc_prefix = iconfig["ion_chamber"]["scaler"]["ioc"]
record_prefix = iconfig["ion_chamber"]["scaler"]["record"]
pv_prefix = f"{ioc_prefix}:{record_prefix}"


class SensitivityPositioner(PVPositionerPC):
    setpoint = Cpt(EpicsSignal, ".VAL")
    readback = Cpt(EpicsSignal, ".VAL")


class SensitivityLevelPositioner(PseudoPositioner):
    values = [1, 2, 5, 10, 20, 50, 100, 200, 500]
    units = ["pA/V", "nA/V", "µA/V", "mA/V"]

    sens_level = Cpt(PseudoSingle, limits=(0, 27))

    # Sensitivity settings
    sens_unit = Cpt(SensitivityPositioner, ":sens_unit", kind="config", settle_time=0.1)
    sens_value = Cpt(SensitivityPositioner, ":sens_num", kind="config", settle_time=0.1)

    @pseudo_position_argument
    def forward(self, target_gain_level):
        "Given a target energy, transform to the mono and ID energies."
        new_level = target_gain_level.sens_level
        new_value = new_level % len(self.values)
        new_unit = int(new_level / len(self.values))
        return self.RealPosition(
            sens_value=new_value,
            sens_unit=new_unit,
        )

    @real_position_argument
    def inverse(self, sensitivity):
        "Given a position in mono and ID energy, transform to the target energy."
        new_gain = sensitivity.sens_value + sensitivity.sens_unit * len(self.values)
        return self.PseudoPosition(sens_level=new_gain)


@registry.register
class IonChamber(Device):
    """An ion chamber at a spectroscopy beamline.

    Also includes the pre-amplifier as ``.pre_amp``.

    Attributes
    ==========

    prefix
      The PV prefix of the overall scaler.
    scaler_ch
      The number (1-index) of the channel on the scaler. 1 is the
      timer, so your channel number should start at 2.

    """

    ch_num: int = 0
    _statuses = {}
    count = FCpt(Signal, "{scaler_prefix}.CNT", trigger_value=1, kind=Kind.omitted)
    raw_counts = FCpt(SignalRO, "{prefix}.S{ch_num}", kind="hinted")
    volts = FCpt(SignalRO, "{prefix}_calc{ch_num}.VAL", kind="hinted")
    sensitivity = FCpt(SensitivityLevelPositioner, "{preamp_prefix}", kind="config")
    read_attrs = ["raw_counts", "volts", "sensitivity_sens_level"]
    # configuration_attrs = ["sensitivity_sens_level", "sensitivity_sens_value", "sensitivity_sens_unit"]

    def __init__(self, prefix, ch_num, name, preamp_prefix=None, scaler_prefix=None, voltage_pv=None, *args, **kwargs):
        # Set up the channel number for this scaler channel
        if ch_num < 1:
            raise ValueError(f"Scaler channels must be greater than 0: {ch_num}")
        self.ch_num = ch_num
        self.ch_char = chr(64 + ch_num)
        # Determine which prefix to use for the scaler
        if scaler_prefix is not None:
            self.scaler_prefix = scaler_prefix
        else:
            self.scaler_prefix = prefix
        # Determine pv for the voltage (e.g. user calc record)
        self.voltage_pv = voltage_pv
        # Save an epics path to the preamp
        if preamp_prefix is None:
            preamp_prefix = prefix
        self.preamp_prefix = preamp_prefix
        # Initialize all the other Device stuff
        super().__init__(prefix=prefix, name=name, *args, **kwargs)

    def change_sensitivity(self, step) -> status.Status:
        new_sens_level = self.sensitivity.sens_level.readback.get() + step
        try:
            status = self.sensitivity.sens_level.set(new_sens_level)
        except ValueError:
            raise exceptions.GainOverflow(self)
        return status

    def increase_gain(self) -> Sequence[status.Status]:
        """Increase the gain (descrease the sensitivity) of the ion chamber's
        pre-amp.

        Returns
        =======
        statuses
          Ophyd status objects for the value and gain of the
          sensitivity in the pre-amp.

        """
        return self.change_sensitivity(-1)

    def decrease_gain(self) -> Sequence[status.Status]:
        """Decrease the gain (increase the sensitivity) of the ion chamber's
        pre-amp.

        Returns
        =======
        statuses
          Ophyd status objects for the value and gain of the
          sensitivity in the pre-amp.

        """
        return self.change_sensitivity(1)

    def trigger(self, *args, **kwargs):
        # Figure out if there's already a trigger active
        previous_status = self._statuses.get(self.scaler_prefix)
        is_idle = previous_status is None or previous_status.done
        # Trigger the detector if not already running, and update the status dict
        if is_idle:
            new_status = super().trigger(*args, **kwargs)
            self._statuses[self.scaler_prefix] = new_status
        else:
            new_status = previous_status
        return new_status


@registry.register
class IonChamberWithOffset(IonChamber):
    offset = FCpt(SignalRO, "{prefix}_offset0.{ch_char}")
    net_counts = FCpt(SignalRO, "{prefix}_netA.{ch_char}")


conf = load_config()
preamp_ioc = conf["ion_chamber"]["preamp"]["ioc"]
vme_ioc = conf["ion_chamber"]["scaler"]["ioc"]
for name, config in conf["ion_chamber"].items():
    # Define ion chambers
    if name not in ["scaler", "preamp"]:
        ch_num = config["scaler_channel"]
        preamp_prefix = f"{preamp_ioc}:{config['preamp_record']}"
        voltage_pv = f"{vme_ioc}:userCalc{ch_num-1}"
        ic = IonChamber(
            prefix=pv_prefix,
            ch_num=config["scaler_channel"],
            name=name,
            voltage_pv=voltage_pv,
            preamp_prefix=preamp_prefix,
            labels={"ion_chambers"},
        )
        log.info(f"Created ion chamber: {ic}")
