import time

import pytest
from ophyd.sim import instantiate_fake_device
from ophyd import PVPositioner

from haven.instrument.energy_positioner import EnergyPositioner, load_energy_positioner


@pytest.fixture()
def positioner():
    positioner = instantiate_fake_device(
        EnergyPositioner,
        name="energy",
        mono_prefix="255idMono:",
        undulator_prefix="S255ID:",
    )
    positioner.monochromator.energy._use_limits = False
    positioner.monochromator.energy.user_setpoint._use_limits = False
    return positioner


def test_set_energy(positioner):
    # Set up dependent values
    positioner.monochromator.id_offset.set(150).wait(timeout=3)
    # Change the energy
    positioner.set(10000, timeout=3)
    # Check that all the sub-components were set properly
    assert positioner.monochromator.energy.get().user_setpoint == 10000
    assert positioner.undulator.energy.get().setpoint == 10150


def test_load_energy_positioner(sim_registry):
    load_energy_positioner()
    energy = sim_registry['energy']
    assert isinstance(energy, PVPositioner)
    assert hasattr(energy, "monochromator")
    assert hasattr(energy, "undulator")


# def test_pseudo_to_real_positioner(positioner):
#     positioner.energy.set(10000, timeout=5.0)
#     assert positioner.get(use_monitor=False).mono_energy.user_setpoint == 10000
#     positioner.id_offset.set(230)
#     time.sleep(0.1)
#     # Move the energy positioner
#     positioner.energy.set(5000)
#     time.sleep(0.1)  # Caproto breaks pseudopositioner status
#     # Check that the mono and ID are both moved
#     assert positioner.get(use_monitor=False).mono_energy.user_setpoint == 5000
#     expected_id_energy = 5.0 + positioner.id_offset.get(use_monitor=False) / 1000
#     assert positioner.get(use_monitor=False).id_energy.setpoint == expected_id_energy


def test_real_to_pseudo_positioner(positioner):
    positioner.monochromator.energy.user_readback._readback = 5000.0
    # Check that the pseudo single is updated
    assert positioner.get(use_monitor=False).readback == 5000.0


# -----------------------------------------------------------------------------
# :author:    Mark Wolfman
# :email:     wolfman@anl.gov
# :copyright: Copyright © 2023, UChicago Argonne, LLC
#
# Distributed under the terms of the 3-Clause BSD License
#
# The full license is in the file LICENSE, distributed with this software.
#
# DISCLAIMER
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# -----------------------------------------------------------------------------
