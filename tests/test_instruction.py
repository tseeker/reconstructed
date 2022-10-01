"""Tests for the instruction base class."""
import pytest
from unittest import mock

from . import reconstructed


class _Instruction(reconstructed.RcInstruction):
    """An instruction with fake implementations for abstract methods."""

    def parse_action(self, record):
        pass

    def execute_action(self, host_name, variables):
        pass


_ACTION_NAME = "this-is-a-test"
"""Name of the test action."""

_INSTR_REPR = _ACTION_NAME + "()"
"""Expected representation of the instruction without flow control."""


@pytest.fixture
def instr():
    """Create a mock instruction suitable for testing."""
    return _Instruction(
        mock.MagicMock(), mock.MagicMock(), mock.MagicMock(), _ACTION_NAME
    )


# ------------------------------------------------------------------------------


def test_default_repr_instruction_only(instr: _Instruction):
    """Default representation returns action followed by ``()``."""
    rv = instr.repr_instruction_only()
    assert rv == _INSTR_REPR


class TestRepr:
    """Tests for the ``__repr__`` method."""

    @pytest.fixture
    def instr(self):
        """Create a mock instruction suitable for testing."""
        instr = _Instruction(
            mock.MagicMock(), mock.MagicMock(), mock.MagicMock(), _ACTION_NAME
        )
        instr.repr_instruction_only = mock.MagicMock(return_value=_INSTR_REPR)
        return instr

    def test_repr_no_flow(self, instr: _Instruction):
        """``repr()`` returns default representation if there is no flow \
                control or variables."""
        rv = repr(instr)
        assert rv == _INSTR_REPR

    def test_repr_condition(self, instr: _Instruction):
        """``repr()`` includes the condition's string if it is defined."""
        instr._condition = "test"
        rv = repr(instr)
        assert rv == "{when=" + repr(instr._condition) + "}" + _INSTR_REPR

    def test_repr_loop(self, instr: _Instruction):
        """``repr()`` includes information about the loop's data and variable \
                name if they are defined."""
        instr._loop = [1, 2, 3]
        instr._loop_var = "test"
        rv = repr(instr)
        assert rv == (
            "{loop="
            + repr(instr._loop)
            + ", loop_var="
            + repr(instr._loop_var)
            + "}"
            + _INSTR_REPR
        )

    def test_repr_vars(self, instr: _Instruction):
        """``repr()`` includes information about variables if at least one \
                variable is defined."""
        instr._vars = {"a": 1}
        rv = repr(instr)
        assert rv == "{vars=" + repr(instr._vars) + "}" + _INSTR_REPR

    @pytest.mark.parametrize("eo_value", (True, False))
    def test_repr_runonce(self, instr: _Instruction, eo_value: bool):
        """``repr()`` includes information about ``run_once``."""
        instr._executed_once = eo_value
        rv = repr(instr)
        assert rv == "{run_once}" + _INSTR_REPR

    def test_repr_everything(self, instr: _Instruction):
        """``repr()`` includes information about all flow controls and \
                variables."""
        instr._executed_once = True
        instr._loop = [1]
        instr._loop_var = "test"
        instr._condition = "test"
        instr._vars = {"a": 1}
        rv = repr(instr)
        assert rv.startswith("{")
        assert rv.endswith("}" + _INSTR_REPR)
        for what in ("when=", "loop=", "loop_var=", "run_once", "vars="):
            assert "{" + what in rv or ", " + what in rv, f"element '{what}' not found"


# ------------------------------------------------------------------------------


def test_default_dump_instruction(instr: _Instruction):
    """The default instruction-only dump returns a list that contains \
            the default instruction representation."""
    instr.repr_instruction_only = mock.MagicMock()
    rv = instr.dump_instruction()
    assert rv == [instr.repr_instruction_only.return_value]


class TestDump:
    """Tests for the ``dump()`` method."""

    @pytest.fixture
    def instr(self):
        """Create a mock instruction suitable for testing."""
        instr = _Instruction(
            mock.MagicMock(), mock.MagicMock(), mock.MagicMock(), _ACTION_NAME
        )
        instr.dump_instruction = mock.MagicMock(return_value=[_INSTR_REPR])
        return instr

    def test_dump_instr_only(self, instr: _Instruction):
        """The full dump only contains the instruction dump if there are no \
                flow controls or local variables."""
        rv = instr.dump()
        assert rv == [_INSTR_REPR]

    def test_dump_condition(self, instr: _Instruction):
        """Conditions cause a dump entry to be generated."""
        instr._condition = "test"
        rv = instr.dump()
        assert rv[-1] == _INSTR_REPR
        assert "{when: " + repr(instr._condition) + "}" in rv

    def test_dump_loop(self, instr: _Instruction):
        """Loops cause a dump entry to be generated."""
        instr._loop = [1, 2, 3]
        instr._loop_var = "test"
        rv = instr.dump()
        assert rv[-1] == _INSTR_REPR
        assert "{loop[" + instr._loop_var + "]: " + repr(instr._loop) + "}" in rv

    @pytest.mark.parametrize("eo_value", (True, False))
    def test_dump_runonce(self, instr: _Instruction, eo_value: bool):
        """``dump()`` includes information about ``run_once``."""
        instr._executed_once = eo_value
        rv = instr.dump()
        assert rv[-1] == _INSTR_REPR
        assert "{run_once}" in rv

    def test_dump_vars(self, instr: _Instruction):
        """A dump entry is generated for each defined variable."""
        instr._vars = {"a": 1, "b": 2}
        rv = instr.dump()
        assert rv[-1] == _INSTR_REPR
        assert "{var a=1}" in rv
        assert "{var b=2}" in rv
