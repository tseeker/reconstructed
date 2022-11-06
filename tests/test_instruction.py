"""Unit tests for the instruction base class."""
import pytest
from unittest import mock
from ansible.errors import AnsibleParserError, AnsibleRuntimeError

from . import reconstructed


class _Instruction(reconstructed.RcInstruction):
    """An instruction with fake implementations for abstract methods."""

    def parse_action(self, record):
        pass

    def execute_action(self, host_name, context):
        pass


_ACTION_NAME = "this-is-a-test"
"""Name of the test action."""

_INSTR_REPR = _ACTION_NAME + "()"
"""Expected representation of the instruction without flow control."""


@pytest.fixture
def instr():
    """Create a mock instruction suitable for testing."""
    i = _Instruction(mock.MagicMock(), mock.MagicMock(), mock.MagicMock(), _ACTION_NAME)
    i._templar.available_variables = None
    return i


@pytest.fixture
def variables():
    """Create a mock variable storage object."""
    return mock.MagicMock()


@pytest.fixture
def context(variables):
    """Create a mock execution context."""
    c = mock.MagicMock()
    c.variables = variables
    return c


@pytest.fixture(autouse=True)
def mock_isidentifier():
    reconstructed.isidentifier = mock.MagicMock()
    reconstructed.isidentifier.return_value = True


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


# ------------------------------------------------------------------------------


class TestParse:
    """Tests for the main ``parse()`` method."""

    @pytest.fixture
    def instr(self):
        """Create a mock instruction suitable for testing the ``parse()`` method."""
        instr = _Instruction(
            mock.MagicMock(), mock.MagicMock(), mock.MagicMock(), "stop"
        )
        instr.parse_condition = mock.MagicMock()
        instr.parse_loop = mock.MagicMock()
        instr.parse_vars = mock.MagicMock()
        instr.parse_vars.return_value.keys.return_value = [
            instr.parse_vars.return_value.keys.return_value
        ]
        instr.parse_run_once = mock.MagicMock()
        instr.parse_action = mock.MagicMock()
        return instr

    def test_record_without_action(self, instr):
        """An assertion rejects calls in which the record does not contain an \
                action."""
        with pytest.raises(AssertionError):
            instr.parse({})

    def test_record_with_mismatch_action(self, instr):
        """An assertion rejects calls in which the record contains an action \
                that is different from what the class can handle."""
        with pytest.raises(AssertionError):
            instr.parse({"action": instr._action + "nope"})

    def test_record_with_unknown_fields(self, instr):
        """Unknown fields in the input record cause an Ansible parser error."""
        field = "not a valid field name anyway"
        with pytest.raises(AnsibleParserError):
            instr.parse({"action": instr._action, field: 1})

    def test_action_only(self, instr):
        """Records with only the ``action`` field get parsed."""
        record = {"action": instr._action}
        #
        instr.parse(record)
        #
        instr.parse_condition.assert_called_once_with(record)
        instr.parse_loop.assert_called_once_with(record)
        instr.parse_vars.assert_called_once_with(record)
        assert instr._vars == instr.parse_vars.return_value
        instr.parse_run_once.assert_called_once_with(record)
        assert instr._save == tuple(instr._vars.keys.return_value)
        instr.parse_action.assert_called_once_with(record)

    @pytest.mark.parametrize("action", list(reconstructed.INSTR_OWN_FIELDS.keys()))
    def test_known_fields(self, instr, action):
        """Records with only known fields get parsed."""
        instr._action = action
        record = {"action": action}
        for field in reconstructed.INSTR_COMMON_FIELDS:
            if field != "action":
                record[field] = True
        for field in reconstructed.INSTR_OWN_FIELDS[action]:
            record[field] = True
        #
        instr.parse(record)
        #
        instr.parse_condition.assert_called_once_with(record)
        instr.parse_loop.assert_called_once_with(record)
        instr.parse_vars.assert_called_once_with(record)
        assert instr._vars == instr.parse_vars.return_value
        instr.parse_run_once.assert_called_once_with(record)
        assert instr._save == tuple(instr._vars.keys.return_value)
        instr.parse_action.assert_called_once_with(record)

    def test_save_loop_var(self, instr):
        """If a loop variable is defined, it must be saved."""
        record = {"action": instr._action}
        instr._loop = []
        instr._loop_var = "test"
        #
        instr.parse(record)
        #
        instr.parse_condition.assert_called_once_with(record)
        instr.parse_loop.assert_called_once_with(record)
        instr.parse_vars.assert_called_once_with(record)
        assert instr._vars == instr.parse_vars.return_value
        instr.parse_run_once.assert_called_once_with(record)
        assert instr._save == tuple(instr._vars.keys.return_value) + (instr._loop_var,)
        instr.parse_action.assert_called_once_with(record)


class TestParseCondition:
    """Tests for the ``parse_condition()`` method."""

    def test_no_condition(self, instr):
        """Records that do not contain a ``when`` field do not set the condition."""
        instr.parse_condition({})
        assert instr._condition is None

    def test_invalid_condition(self, instr):
        """Records that contain a ``when`` field that isn't a string cause a \
                parse error and do not set the condition."""
        with pytest.raises(AnsibleParserError):
            instr.parse_condition({"when": ()})
        assert instr._condition is None

    def test_condition(self, instr):
        """Records that contain a ``when`` field that is a string set the condition."""
        cond = "test"
        instr.parse_condition({"when": cond})
        assert instr._condition == cond


class TestParseLoop:
    """Tests for the ``parse_loop()`` method."""

    def test_no_loop(self, instr):
        """No loop set when the record doesn't configure a loop."""
        instr.parse_loop({})
        reconstructed.isidentifier.assert_not_called()
        assert instr._loop is None
        assert instr._loop_var is None

    def test_loopvar_no_loop(self, instr):
        """Parse error if the record configures a loop var without loop."""
        with pytest.raises(AnsibleParserError):
            instr.parse_loop({"loop_var": "test"})
        reconstructed.isidentifier.assert_not_called()
        assert instr._loop is None
        assert instr._loop_var is None

    def test_loop_bad_type(self, instr):
        """Parse error if the record configures a loop with an invalid type."""
        with pytest.raises(AnsibleParserError):
            instr.parse_loop({"loop": {}})
        reconstructed.isidentifier.assert_not_called()
        assert instr._loop is None
        assert instr._loop_var is None

    def test_loopvar_bad_type(self, instr):
        """Parse error if the record configures a loop var with an invalid type."""
        with pytest.raises(AnsibleParserError):
            instr.parse_loop({"loop": "test", "loop_var": {}})
        reconstructed.isidentifier.assert_not_called()
        assert instr._loop is None
        assert instr._loop_var is None

    def test_loopvar_invalid_identifier(self, instr):
        """Parse error if the record configures a loop var with an invalid name."""
        reconstructed.isidentifier.return_value = False
        lv = "test"
        with pytest.raises(AnsibleParserError):
            instr.parse_loop({"loop": "test", "loop_var": lv})
        reconstructed.isidentifier.assert_called_once_with(lv)
        assert instr._loop is None
        assert instr._loop_var is None

    @pytest.mark.parametrize("value", ("test", ["test"]))
    def test_loop_valid(self, instr, value):
        """Condition is copied with default loop variable if it is valid."""
        instr.parse_loop({"loop": value})
        reconstructed.isidentifier.assert_called_once_with(instr.DEFAULT_LOOP_VAR)
        assert instr._loop == value
        assert instr._loop_var == instr.DEFAULT_LOOP_VAR

    def test_loop_with_var(self, instr):
        """Condition and loop var are copied if they are defined and valid."""
        loop = "loop"
        loop_var = "loop var"
        instr.parse_loop({"loop": loop, "loop_var": loop_var})
        reconstructed.isidentifier.assert_called_once_with(loop_var)
        assert instr._loop == loop
        assert instr._loop_var == loop_var


class TestParseVars:
    """Tests for the ``parse_vars()`` method."""

    def test_no_vars(self, instr):
        """No variables are returned if none are configured."""
        rv = instr.parse_vars({})
        assert rv == {}
        reconstructed.isidentifier.assert_not_called()

    def test_empty_vars(self, instr):
        """No variables are returned if the input is empty."""
        rv = instr.parse_vars({"vars": {}})
        assert rv == {}
        reconstructed.isidentifier.assert_not_called()

    def test_invalid_type(self, instr):
        """A parser error occurs if the input has the wrong type."""
        record = {"vars": []}
        with pytest.raises(AnsibleParserError):
            instr.parse_vars(record)
        reconstructed.isidentifier.assert_not_called()

    @pytest.mark.parametrize("bad_id", (1, (), ("x",)))
    def test_invalid_id_type(self, instr, bad_id):
        """A parser error occurs if a variable identifier has the wrong type."""
        record = {"vars": {bad_id: "ok"}}
        with pytest.raises(AnsibleParserError):
            instr.parse_vars(record)
        reconstructed.isidentifier.assert_not_called()

    def test_invalid_identifier(self, instr):
        """A parser error occurs if a variable identifier is not a valid \
                Ansible identifier."""
        reconstructed.isidentifier.return_value = False
        bad_id = "test"
        record = {"vars": {bad_id: "ok"}}
        with pytest.raises(AnsibleParserError):
            instr.parse_vars(record)
        reconstructed.isidentifier.assert_called_once_with(bad_id)

    def test_valid_vars(self, instr):
        """Configured variables are returned if they are valid."""
        record = {"vars": {"a": "ok", "b": [], "c": {}}}
        rv = instr.parse_vars(record)
        assert rv is record["vars"]
        isid_calls = reconstructed.isidentifier.call_args_list
        assert len(isid_calls) == len(record["vars"])
        for key in record["vars"].keys():
            assert mock.call(key) in isid_calls


class TestParseRunOnce:
    """Tests for the ``parse_run_once()`` method."""

    def test_no_runonce(self, instr):
        """No effect unless ``run_once`` is defined."""
        instr.parse_run_once({})
        assert instr._executed_once is None

    @pytest.mark.parametrize("bad_value", (1, "lol", [1], (1,), {"1": "2"}))
    def test_runonce_invalid(self, instr, bad_value):
        """Parse error if ``run_once`` is defined with an invalid type."""
        with pytest.raises(AnsibleParserError):
            instr.parse_run_once({"run_once": bad_value})
        assert instr._executed_once is None

    def test_runonce_false(self, instr):
        """No effect if ``run_once`` is defined but set to ``False``."""
        instr.parse_run_once({"run_once": False})
        assert instr._executed_once is None

    def test_runonce_true(self, instr):
        """Feature enabled if ``run_once`` is defined and set to ``True``."""
        instr.parse_run_once({"run_once": True})
        assert instr._executed_once is False


# ------------------------------------------------------------------------------


class TestRunFor:
    """Tests for the ``run_for()`` method."""

    @pytest.fixture
    def instr(self):
        """Create a mock instruction suitable for testing."""
        instr = _Instruction(
            mock.MagicMock(), mock.MagicMock(), mock.MagicMock(), _ACTION_NAME
        )
        instr.run_iteration = mock.MagicMock()
        instr.evaluate_loop = mock.MagicMock()
        return instr

    def test_run_no_loop(self, instr, context):
        """Running with no loop set causes ``run_iteration()`` to be called."""
        hn = object()
        save = object()
        instr._save = save
        instr._executed_once = None
        #
        rv = instr.run_for(hn, context)
        #
        assert instr._executed_once is None
        context.variables._script_stack_push.assert_called_once_with(save)
        context.variables._script_stack_pop.assert_called_once_with()
        instr.run_iteration.assert_called_once_with(hn, context)
        instr.evaluate_loop.assert_not_called()
        assert rv is instr.run_iteration.return_value

    def test_crash_no_loop(self, instr, context):
        """If ``run_iteration()`` crashes when there is no loop, the stack \
                is popped and the exception is propagated."""
        hn = object()
        save = object()
        instr._save = save
        instr._executed_once = None
        instr.run_iteration.side_effect = RuntimeError
        #
        with pytest.raises(RuntimeError):
            instr.run_for(hn, context)
        #
        assert instr._executed_once is None
        context.variables._script_stack_push.assert_called_once_with(save)
        context.variables._script_stack_pop.assert_called_once_with()
        instr.run_iteration.assert_called_once_with(hn, context)

    def test_run_once_first_time(self, instr, context):
        """The method updates the execution flag and executes the iteration \
                if it is set to run once but hasn't been called yet."""
        hn = object()
        save = object()
        instr._save = save
        instr._executed_once = False
        #
        rv = instr.run_for(hn, context)
        #
        assert instr._executed_once is True
        context.variables._script_stack_push.assert_called_once_with(save)
        context.variables._script_stack_pop.assert_called_once_with()
        instr.run_iteration.assert_called_once_with(hn, context)
        instr.evaluate_loop.assert_not_called()
        assert rv is instr.run_iteration.return_value

    def test_run_once_already_called(self, instr, context):
        """The method returns ``True`` but does nothing if it has already been \
                called."""
        hn = object()
        save = object()
        instr._save = save
        instr._executed_once = True
        #
        rv = instr.run_for(hn, context)
        #
        assert instr._executed_once is True
        context.variables._script_stack_push.assert_not_called()
        context.variables._script_stack_pop.assert_not_called()
        instr.run_iteration.assert_not_called()
        instr.evaluate_loop.assert_not_called()
        assert rv is True

    def test_run_loop(self, instr, context):
        """Running with a loop set causes ``evaluate_loop()`` to be called, \
                followed by a call to ``run_iteration()`` for each value it \
                returned."""
        hn = object()
        save = object()
        lv = object()
        instr._save = save
        instr._executed_once = None
        instr._loop = [1]
        instr._loop_var = lv
        instr.evaluate_loop.return_value = (1, 2, 3)
        #
        rv = instr.run_for(hn, context)
        #
        assert instr._executed_once is None
        context.variables._script_stack_push.assert_called_once_with(save)
        context.variables._script_stack_pop.assert_called_once_with()
        instr.evaluate_loop.assert_called_once_with(hn, context.variables)
        assert context.variables.__setitem__.call_args_list == [
            mock.call(lv, 1),
            mock.call(lv, 2),
            mock.call(lv, 3),
        ]
        assert instr.run_iteration.call_args_list == [
            mock.call(hn, context),
            mock.call(hn, context),
            mock.call(hn, context),
        ]
        assert rv is True

    def test_run_loop_exit(self, instr, context):
        """If ``run_iteration()`` returns a falsy value, the loop is interrupted."""
        hn = object()
        save = object()
        lv = object()
        instr._save = save
        instr._executed_once = None
        instr._loop = [1]
        instr._loop_var = lv
        instr.evaluate_loop.return_value = (1, 2, 3)
        instr.run_iteration.return_value = False
        #
        rv = instr.run_for(hn, context)
        #
        assert instr._executed_once is None
        context.variables._script_stack_push.assert_called_once_with(save)
        context.variables._script_stack_pop.assert_called_once_with()
        instr.evaluate_loop.assert_called_once_with(hn, context.variables)
        assert context.variables.__setitem__.call_args_list == [mock.call(lv, 1)]
        assert instr.run_iteration.call_args_list == [mock.call(hn, context)]
        assert rv is False

    def test_crash_loop(self, instr, context):
        """If ``run_iteration()`` crashes when there is a loop, the stack \
                is popped and the exception is propagated."""
        hn = object()
        save = object()
        lv = object()
        instr._save = save
        instr._executed_once = None
        instr._loop = [1]
        instr._loop_var = lv
        instr.evaluate_loop.return_value = (1, 2, 3)
        instr.run_iteration.side_effect = RuntimeError
        #
        with pytest.raises(RuntimeError):
            instr.run_for(hn, context)
        #
        assert instr._executed_once is None
        context.variables._script_stack_push.assert_called_once_with(save)
        context.variables._script_stack_pop.assert_called_once_with()
        assert context.variables.__setitem__.call_args_list == [mock.call(lv, 1)]
        assert instr.run_iteration.call_args_list == [mock.call(hn, context)]


class TestRunIteration:
    """Tests for the ``run_iteration()`` method."""

    @pytest.fixture
    def instr(self):
        """Create a mock instruction suitable for testing."""
        instr = _Instruction(
            mock.MagicMock(), mock.MagicMock(), mock.MagicMock(), _ACTION_NAME
        )
        instr.compute_locals = mock.MagicMock()
        instr.evaluate_condition = mock.MagicMock()
        instr.execute_action = mock.MagicMock()
        return instr

    def test_run_cond_false(self, instr, context):
        """If the condition is not satisfied, ``True`` is returned but the \
                action is not executed."""
        hn = object()
        instr.evaluate_condition.return_value = False
        #
        rv = instr.run_iteration(hn, context)
        #
        instr.compute_locals.assert_called_once_with(context.variables)
        instr.evaluate_condition.assert_called_once_with(hn, context.variables)
        instr.execute_action.assert_not_called()
        instr._display.vvvvv.assert_not_called()
        assert rv is True

    def test_run_cond_true(self, instr, context):
        """If the condition is satisfied, the action is executed and its \
                return value is returned."""
        hn = object()
        instr.evaluate_condition.return_value = True
        #
        rv = instr.run_iteration(hn, context)
        #
        instr.compute_locals.assert_called_once_with(context.variables)
        instr.evaluate_condition.assert_called_once_with(hn, context.variables)
        instr.execute_action.assert_called_once_with(hn, context)
        instr._display.vvvvv.assert_not_called()
        assert rv is instr.execute_action.return_value

    def test_run_interrupt(self, instr, context):
        """If the condition is satisfied and the action returns ``False``, a \
                debug message is displayed."""
        hn = object()
        instr.evaluate_condition.return_value = True
        instr.execute_action.return_value = False
        #
        rv = instr.run_iteration(hn, context)
        #
        instr.compute_locals.assert_called_once_with(context.variables)
        instr.evaluate_condition.assert_called_once_with(hn, context.variables)
        instr.execute_action.assert_called_once_with(hn, context)
        instr._display.vvvvv.assert_called_once()
        assert rv is False


class TestEvaluateCondition:
    """Tests for the ``evaluate_condition()`` method."""

    @pytest.fixture
    def instr(self):
        """Create a mock instruction suitable for testing."""
        instr = _Instruction(
            mock.MagicMock(), mock.MagicMock(), mock.MagicMock(), _ACTION_NAME
        )
        instr._templar.environment.variable_start_string = "<--"
        instr._templar.environment.variable_end_string = "-->"
        return instr

    @pytest.fixture(autouse=True)
    def boolean(self):
        """The Ansible-provided ``boolean`` utility function."""
        reconstructed.boolean = mock.MagicMock()
        return reconstructed.boolean

    def test_no_condition(self, instr, boolean):
        """When there is no condition, ``True`` is returned without the \
                template being used."""
        instr._condition = None
        variables = object()
        host_name = object()
        #
        rv = instr.evaluate_condition(host_name, variables)
        #
        assert rv is True
        instr._templar.template.assert_not_called()
        boolean.assert_not_called()

    def test_condition_value(self, instr, boolean):
        """When there is a condition, the template is evaluated, and the \
                results are converted to a boolean and returned."""
        cond = "abc"
        variables = object()
        host_name = object()
        instr._condition = cond
        #
        rv = instr.evaluate_condition(host_name, variables)
        #
        assert instr._templar.available_variables is variables
        instr._templar.template.assert_called_once_with(
            f"<--{cond}-->", disable_lookups=False
        )
        boolean.assert_called_once_with(instr._templar.template.return_value)
        assert rv is boolean.return_value


class TestComputeLocals:
    """Tests for the ``compute_locals()`` method."""

    @pytest.fixture
    def instr(self):
        """Create a mock instruction suitable for testing."""
        instr = _Instruction(
            mock.MagicMock(), mock.MagicMock(), mock.MagicMock(), _ACTION_NAME
        )
        instr._templar.template.side_effect = lambda x: x
        return instr

    def test_compute_locals(self, instr, variables):
        """Templates are evaluated for each local variable."""
        instr._templar.available_variables = None
        obj1, obj2, obj3, obj4 = object(), object(), object(), object()
        instr._vars = {obj1: obj2, obj3: obj4}
        #
        instr.compute_locals(variables)
        #
        assert instr._templar.available_variables is variables
        assert instr._templar.template.call_args_list == [
            mock.call(obj2),
            mock.call(obj4),
        ]
        assert variables.__setitem__.call_args_list == [
            mock.call(obj1, obj2),
            mock.call(obj3, obj4),
        ]


class TestEvaluateLoop:
    """Tests for the ``evaluate_loop()`` method."""

    def test_list_returned(self, instr):
        """When a list is returned by the template's evaluation, it is \
                passed on by the method."""
        iv = object()
        v = object()
        erv = []
        instr._loop = iv
        instr._templar.available_variables = None
        instr._templar.template.return_value = erv
        #
        rv = instr.evaluate_loop("test", v)
        #
        assert instr._templar.available_variables is v
        instr._templar.template.assert_called_once_with(iv, disable_lookups=False)
        assert rv is erv

    def test_bad_return_type(self, instr):
        """When something that isn't a list is returned by the template's \
                evaluation, an Ansible runtime error occurs."""
        iv = object()
        v = object()
        erv = {}
        instr._loop = iv
        instr._templar.available_variables = None
        instr._templar.template.return_value = erv
        #
        with pytest.raises(AnsibleRuntimeError):
            instr.evaluate_loop("test", v)
        #
        assert instr._templar.available_variables is v
        instr._templar.template.assert_called_once_with(iv, disable_lookups=False)


# ------------------------------------------------------------------------------


class TestParseGroupName:
    """Tests for the ``parse_group_name()`` helper method."""

    @pytest.fixture(autouse=True)
    def mock_constants(self):
        reconstructed.C = mock.MagicMock()

    def test_missing_field(self, instr):
        """An error occurs if the field is missing."""
        with pytest.raises(AnsibleParserError):
            instr.parse_group_name({}, "test")
        instr._templar.is_possibly_template.assert_not_called()
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.assert_not_called()

    @pytest.mark.parametrize("bad_value", (1, [1], (1,), {"1": "2"}))
    def test_invalid_type(self, instr, bad_value):
        """An error occurs if the field has an incorrect type."""
        name = "test"
        with pytest.raises(AnsibleParserError):
            instr.parse_group_name({name: bad_value}, name)
        instr._templar.is_possibly_template.assert_not_called()
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.assert_not_called()

    def test_may_be_template(self, instr):
        """``True`` and value are returned if it may be a template."""
        name = "test"
        value = "  ament  "
        instr._templar.is_possibly_template.return_value = True
        rv = instr.parse_group_name({name: value}, name)
        assert rv == (True, value)
        instr._templar.is_possibly_template.assert_called_once_with(value)
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.assert_not_called()

    def test_not_template_bad(self, instr):
        """Value must be a valid variable name if it cannot possibly be a template."""
        name = "test"
        value = "ament"
        instr._templar.is_possibly_template.return_value = False
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.return_value = True
        with pytest.raises(AnsibleParserError):
            instr.parse_group_name({name: value}, name)
        instr._templar.is_possibly_template.assert_called_once_with(value)
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.assert_called_once()

    def test_not_template_ok(self, instr):
        """``False`` and value are returned if it isn't a template."""
        name = "test"
        value = "ament"
        instr._templar.is_possibly_template.return_value = False
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.return_value = False
        rv = instr.parse_group_name({name: value}, name)
        assert rv == (False, value)
        instr._templar.is_possibly_template.assert_called_once_with(value)
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.assert_called_once()

    def test_not_template_strip(self, instr):
        """Value is stripped if it cannot possibly be a template."""
        name = "test"
        value = "ament"
        param = "    " + value + "    "
        instr._templar.is_possibly_template.return_value = False
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.return_value = False
        rv = instr.parse_group_name({name: param}, name)
        assert rv == (False, value)
        instr._templar.is_possibly_template.assert_called_once_with(param)
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.assert_called_once()


class TestGetTemplatedGroup:
    """Tests for the ``get_templated_group`` helper method."""

    @pytest.fixture(autouse=True)
    def mock_constants(self):
        reconstructed.C = mock.MagicMock()

    def test_not_a_template(self, instr, variables):
        name = "abc"
        rv = instr.get_templated_group(variables, False, name, False)
        assert rv is name
        assert instr._templar.available_variables is None
        instr._templar.template.assert_not_called()

    def test_must_exist_ok(self, instr, variables):
        name = "abc"
        instr._inventory.groups = {name: 1}
        rv = instr.get_templated_group(variables, False, name, True)
        assert rv is name

    def test_must_exist_nok(self, instr, variables):
        name = "abc"
        instr._inventory.groups = {name + "nope": 1}
        with pytest.raises(AnsibleRuntimeError):
            instr.get_templated_group(variables, False, name, True)

    def test_template_bad_type(self, instr, variables):
        name = "abc"
        instr._templar.template.return_value = ()
        #
        with pytest.raises(AnsibleRuntimeError):
            instr.get_templated_group(variables, True, name)
        #
        assert instr._templar.available_variables is variables
        instr._templar.template.assert_called_once_with(name)
        reconstructed.C.findall.assert_not_called()

    def test_template_invalid_name(self, instr):
        name = "abc"
        instr._templar.template.return_value = name + "rv"
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.return_value = True
        #
        with pytest.raises(AnsibleRuntimeError):
            instr.get_templated_group(variables, True, name)
        #
        assert instr._templar.available_variables is variables
        instr._templar.template.assert_called_once_with(name)
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.assert_called_once_with(
            name + "rv"
        )

    @pytest.mark.parametrize(
        "t_input, t_output", [("abc", "abc"), ("   abc   ", "abc")]
    )
    def test_template_values(self, instr, variables, t_input, t_output):
        name = "abc"
        instr._templar.template.return_value = t_input
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.return_value = False
        #
        rv = instr.get_templated_group(variables, True, name)
        #
        assert instr._templar.available_variables is variables
        instr._templar.template.assert_called_once_with(name)
        reconstructed.C.INVALID_VARIABLE_NAMES.findall.assert_called_once_with(t_output)
        assert rv == t_output
