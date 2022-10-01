import abc
import copy
from collections.abc import MutableMapping

from ansible import constants as C
from ansible.errors import AnsibleParserError, AnsibleRuntimeError, AnsibleError
from ansible.module_utils.six import string_types
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.utils.vars import isidentifier
from ansible.plugins.inventory import BaseInventoryPlugin

DOCUMENTATION = """
    name: reconstructed
    short_description: A plugin that allows the dynamic construction of groups
    author: Emmanuel BENOÎT
    description:
    - This inventory plugin allows the construction of groups, the optional
      assignment of hosts to these groups and the computation of arbitrary
      facts.
    options:
      plugin:
        description:
        - Token that ensures this is a source file for the C(group_creator)
          plugin.
        required: True
        choices: ['reconstructed']
      instructions:
        description:
        - The list of instructions to be executed in order to generate the
          inventory parts. Each instruction is represented as a dictionnary
          with at least an C(action) field which determines which instruction
          must be executed. The instructions will be executed once for each
          inventory host.
        - Instructions may include various fields that act as control flow.
        - If the C(loop) field is present, it must contain a list (or a Jinja
          template that will return a list). The instruction will be repeated
          for each value in the list. The C(loop_var) field may be added to
          specify the name of the variable into which the current value will
          be written; by default the C(item) variable will be used. Once the
          loop execution ends, the loop variable's previous state is restored.
        - The C(when) field, if present, must contain a Jinja expression
          representing a condition which will be checked before the instruction
          is executed.
        - The C(run_once) field will ensure that the instuction it is attached
          to will only run one time at most.
        - The C(action) field must be set to one of the following values.
        - The C(block) action is another form of flow control, which can be
          used to repeat multiple instructions or make them obey a single
          conditional. The instruction must include a C(block) field, containing
          the list of instructions which are part of the block. In addition, it
          may have a C(rescue) field, containing a list of instructions which
          will be executed on error, and C(always), which may contain a list
          of instructions to execute in all cases. If the C(locals) field is
          defined, it must contain a table of local variables to define. Any
          local variable defined by the instructions under C(block), C(rescue)
          or C(always) will go out of scope once the block finishes executing,
          and the previous values, if any, will be restored.
        - C(create_group) creates a group. The name of the group must be
          provided using the C(group) field, which must be a valid name or a
          Jinja template that evaluates to a valid name. In addition, a
          C(parent) field containting the name of a single, existing parent
          group (or a Jinja template generating the name) may be provided.
          Finally, the C(add_host) field may be set to a truthy value if the
          current host must be added to the new group.
        - C(add_child) adds a child group to another group. The name of the
          group being added must be provided in the C(child) entry, while
          the name of the parent must be provided in the C(group) entry. Both
          groups must exist. In addition, the names may be specified using
          Jinja templates.
        - C(add_host) adds the current inventory host to a group. The name
          of the group must be provided in the C(group) entry. The group
          must exist.
        - C(fail) causes the computations for the current host to stop with
          an error. The error message may be specified in the C(message)
          entry; if present, it will be evaluated using Jinja.
        - C(set_fact) and C(set_var) create a fact and a local variable,
          respectively. Local variables will only be kept during the execution
          of the script for the current host, while facts will be added to the
          host's data. The C(name) entry specifies the name of the fact or
          variable while the C(value) entry specifies its value. Both may be
          Jinja templates.
        - C(stop) stops processing the list of instructions for the current
          host.
        type: list
        elements: dict
        required: True
      strictness:
        description:
        - The C(host) setting will cause an error to skip the host being
          processed, and the C(full) setting will abort the execution
          altogether.
        required: False
        choices: ['host', 'full']
        default: host
"""

INSTR_COMMON_FIELDS = ("action", "loop", "loop_var", "run_once", "vars", "when")
"""Fields that may be present on all instructions."""

INSTR_OWN_FIELDS = {
    "add_child": ("group", "child"),
    "add_host": ("group",),
    "block": ("block", "rescue", "always", "locals"),
    "create_group": ("group", "parent", "add_host"),
    "fail": ("msg",),
    "set_fact": ("name", "value"),
    "set_var": ("name", "value"),
    "stop": (),
}
"""Fields that are specific to each instruction."""

INSTR_FIELDS = {k: set(v + INSTR_COMMON_FIELDS) for k, v in INSTR_OWN_FIELDS.items()}
"""All supported fields for each instruction, including common and specific fields."""


class VariableStorage(MutableMapping):
    """Variable storage and cache.

    This class implements storage for local variables, with the ability to save
    some of them and then restore them. It also implements a cache that combines
    both local variables and host facts.
    """

    def __init__(self, host_vars):
        """Initialize the cache using the specified mapping of host variables.

        Args:
            host_vars: the host variables
        """
        self._host_vars = host_vars
        self._script_vars = {}
        self._script_stack = []
        self._cache = host_vars.copy()

    def _script_stack_push(self, variables):
        """Push the state of some local variables to the stack.

        This method will add a record containing the state of some variables to
        the stack so it may be restored later. The state for a single variable
        consists in a flag indicating whether the variable existed or not, and
        its value if it did.

        Args:
            variables: an iterable of variable names whose state must be pushed
        """
        data = {}
        for v in variables:
            if v in self._script_vars:
                se = (True, copy.copy(self._script_vars[v]))
            else:
                se = (False, None)
            data[v] = se
        self._script_stack.append(data)

    def _script_stack_pop(self):
        """Restore the state of local variables from the stack.

        This method will restore state entries that were saved by
        :py:meth:`_script_stack_push`. Local variables that didn't exist then
        will be deleted, while variables which actually existed will be
        restored. The cache will be reset.
        """
        restore = self._script_stack.pop()
        unchanged = 0
        for vn, vv in restore.items():
            existed, value = vv
            if existed:
                self._script_vars[vn] = value
            elif vn in self._script_vars:
                del self._script_vars[vn]
            else:
                unchanged += 1
        if unchanged != len(restore):
            self._cache = self._host_vars.copy()
            self._cache.update(self._script_vars)

    def _set_host_var(self, name, value):
        """Set a host variable.

        This method sets the value of a host variable in the appropriate
        mapping, and updates the cache as will unless a local variable with the
        same name exists.

        Note: the actual inventory is not modified, only the local copy of
        host variables is.

        Args:
            name: the name of the variable
            value: the value of the variable
        """
        self._host_vars[name] = value
        if name not in self._script_vars:
            self._cache[name] = value

    def __getitem__(self, k):
        return self._cache[k]

    def __setitem__(self, k, v):
        self._script_vars[k] = v
        self._cache[k] = v

    def __delitem__(self, k):
        del self._script_vars[k]
        if k in self._host_vars:
            self._cache[k] = self._host_vars[k]
        else:
            del self._cache[k]

    def __iter__(self):
        return self._cache.__iter__()

    def __len__(self):
        return len(self._cache)

    def keys(self):
        return self._cache.keys()

    def items(self):
        return self._cache.items()

    def values(self):
        return self._cache.values()


class RcInstruction(abc.ABC):
    """An instruction that can be executed by the plugin."""

    DEFAULT_LOOP_VAR = "item"
    """The name of the default loop variable."""

    def __init__(self, inventory, templar, display, action):
        self._inventory = inventory
        self._templar = templar
        self._display = display
        self._action = action
        self._condition = None
        self._executed_once = None
        self._loop = None
        self._loop_var = None
        self._vars = {}
        self._save = None

    def __repr__(self):
        """Builds a compact debugging representation of the instruction, \
                including any conditional or iteration clause."""
        flow = []
        if self._condition is not None:
            flow.append("when=%s" % (repr(self._condition),))
        if self._loop is not None:
            flow.append(
                "loop=%s, loop_var=%s" % (repr(self._loop), repr(self._loop_var))
            )
        if len(self._vars) != 0:
            flow.append("vars=%s" % (repr(self._vars),))
        if self._executed_once is not None:
            flow.append("run_once")
        if flow:
            output = "{%s}" % (", ".join(flow),)
        else:
            output = ""
        output += self.repr_instruction_only()
        return output

    def repr_instruction_only(self):
        """Builds a compact debugging representation of the instruction itself."""
        return "%s()" % (self._action,)

    def dump(self):
        """Builds a representation of the instruction over multiple lines.

        This method generates a representation of the instruction, including
        any conditional or iteration clause, over multiple lines. It is meant
        to be used when generating a dump of the parsed program for high
        verbosity values.

        Returns:
            a list of strings (one for each line)
        """
        output = []
        if self._executed_once is not None:
            output.append("{run_once}")
        if self._loop is not None:
            output.append("{loop[%s]: %s}" % (self._loop_var, repr(self._loop)))
        for var in self._vars:
            output.append("{var %s=%s}" % (var, repr(self._vars[var])))
        if self._condition is not None:
            output.append("{when: %s}" % (repr(self._condition),))
        output.extend(self.dump_instruction())
        return output

    def dump_instruction(self):
        """Builds the multi-line debugging representation of the instruction.

        This method returns a list of strings that correspond to the output
        lines that represent the instruction.

        Returns:
            a list of strings (one for each line)
        """
        return [self.repr_instruction_only()]

    def parse(self, record):
        """Parse the instruction's record.

        This method ensures that no unsupported fields are present in the
        instruction's record. It then extracts the conditional clause and the
        iteration clause, if they are present. Finally it calls ``parse_action``
        in order to extract the instruction itself.

        Args:
            record: the dictionnary that contains the instruction
        """
        assert "action" in record and record["action"] == self._action
        # Ensure there are no unsupported fields
        extra_fields = set(record.keys()).difference(INSTR_FIELDS[self._action])
        if extra_fields:
            raise AnsibleParserError(
                "%s: unsupported fields: %s" % (self._action, ", ".join(extra_fields))
            )
        # Extract the loop, condition and local variable clauses
        self.parse_condition(record)
        self.parse_loop(record)
        self._vars = self.parse_vars(record)
        self.parse_run_once(record)
        # Cache the list of variables to save before execution
        save = list(self._vars.keys())
        if self._loop is not None:
            save.append(self._loop_var)
        self._save = tuple(save)
        # Process action-specific fields
        self.parse_action(record)

    def parse_condition(self, record):
        """Parse the ``when`` clause of an instruction.

        If the ``when`` clause is present, ensure it contains a string then
        store it.

        Args:
            record: the YAML data

        Raises:
            AnsibleParserError: if the ``when`` clause is present but does not \
                    contain a string
        """
        if "when" not in record:
            return
        if not isinstance(record["when"], string_types):
            raise AnsibleParserError(
                "%s: 'when' clause is not a string" % (self._action,)
            )
        self._condition = record["when"]

    def parse_loop(self, record):
        """Parse the ``loop`` and ``loop_var`` clauses of an instruction.

        Check for proper usage of both the ``loop`` and ``loop_var`` clauses,
        then extract the values and store them.

        Args:
            record: the instruction's YAML data

        Raises:
            AnsibleParserError: when ``loop_var`` is being used without \
                ``loop``, when the type of either is incorrect, or when the \
                value of ``loop_var`` is not a valid identifier.
        """
        if "loop" not in record:
            if "loop_var" in record:
                raise AnsibleParserError(
                    "%s: 'loop_var' clause found without 'loop'" % (self._action,)
                )
            return
        loop = record["loop"]
        if not isinstance(loop, string_types + (list,)):
            raise AnsibleParserError(
                "%s: 'loop' clause is neither a string nor a list" % (self._action,)
            )
        loop_var = record.get("loop_var", RcInstruction.DEFAULT_LOOP_VAR)
        if not isinstance(loop_var, string_types):
            raise AnsibleParserError(
                "%s: 'loop_var' clause is not a string" % (self._action,)
            )
        if not isidentifier(loop_var):
            raise AnsibleParserError(
                "%s: 'loop_var' value '%s' is not a valid identifier"
                % (self._action, loop_var)
            )
        self._loop = loop
        self._loop_var = loop_var

    def parse_vars(self, record):
        """Parse local variable definitions from the record.

        This method checks for a ``vars`` section in the YAML data, and extracts
        it if it exists.

        Args:
            record: the YAML data for the instruction

        Returns:
            a dictionnary that contains the variable definitions

        Raises:
            AnsibleParserError: when the ``vars`` entry is invalid or contains \
                    invalid definitions
        """
        if "vars" not in record:
            return {}
        if not isinstance(record["vars"], dict):
            raise AnsibleParserError(
                "%s: 'vars' should be a dictionnary" % (self._action,)
            )
        for k, v in record["vars"].items():
            if not isinstance(k, string_types):
                raise AnsibleParserError(
                    "%s: vars identifiers must be strings" % (self._action,)
                )
            if not isidentifier(k):
                raise AnsibleParserError(
                    "%s: '%s' is not a valid identifier" % (self._action, k)
                )
        return record["vars"]

    def parse_run_once(self, record):
        """Parse an instruction's ``run_once`` clause.

        Args:
            record: the YAML data for the instruction

        Raises:
            AnsibleParserError: when the clause is present but does not \
                contain a truthy value
        """
        if "run_once" not in record:
            return
        if not isinstance(record["run_once"], bool):
            raise AnsibleParserError(
                "%s: run_once must be a truthy value" % (self._action,)
            )
        if record["run_once"]:
            self._executed_once = False

    def parse_group_name(self, record, name):
        """Parse a field containing the name of a group, or a template.

        This helper method may be used by implementations to extract either a
        group name or a template from a field. If the string cannot possibly be
        a Jinja template, it will be stripped of extra spaces then checked for
        invalid characters.

        Args:
            record: the dictionnary that contains the instruction
            name: the name of the field to read

        Returns:
            a tuple consisting of a boolean that indicates whether the string
            may be a template or not, and the string itself.
        """
        if name not in record:
            raise AnsibleParserError("%s: missing '%s' field" % (self._action, name))
        group = record[name]
        if not isinstance(group, string_types):
            raise AnsibleParserError(
                "%s: '%s' field must be a string" % (self._action, name)
            )
        may_be_template = self._templar.is_possibly_template(group)
        if not may_be_template:
            group = group.strip()
            if C.INVALID_VARIABLE_NAMES.findall(group):
                raise AnsibleParserError(
                    "%s: invalid group name '%s' in field '%s'"
                    % (self._action, group, name)
                )
        return may_be_template, group

    @abc.abstractmethod
    def parse_action(self, record):
        """Parse the instruction-specific fields.

        This method must be overridden to read all necessary data from the input
        record and configure the instruction.

        Args:
            record: the dictionnary that contains the instruction
        """
        raise NotImplementedError

    def run_for(self, host_name, variables):
        """Execute the instruction for a given host.

        This method is the entry point for instruction execution. Depending on
        whether an iteration clause is present or not, it will either call
        :py:meth:`run_iteration` directly or evaluate the loop data then run it
        once for each item, after setting the loop variable.

        Args:
            host_name: the name of the host to execute the instruction for
            variables: the variable storage instance

        Returns:
            ``True`` if execution must continue, ``False`` if it must be
            interrupted
        """
        if self._executed_once is True:
            return True
        if self._executed_once is False:
            self._executed_once = True
        # Save previous loop and local variables state
        variables._script_stack_push(self._save)
        try:
            # Instructions without loops
            if self._loop is None:
                self._display.vvvv("%s : running action %s" % (host_name, self._action))
                return self.run_iteration(host_name, variables)
            # Loop over all values
            for value in self.evaluate_loop(host_name, variables):
                self._display.vvvv(
                    "%s : running action %s for item %s"
                    % (host_name, self._action, repr(value))
                )
                variables[self._loop_var] = value
                if not self.run_iteration(host_name, variables):
                    return False
            return True
        finally:
            # Restore loop variable state
            variables._script_stack_pop()

    def run_iteration(self, host_name, variables):
        """Check the condition if it exists, then run the instruction.

        Args:
            host_name: the name of the host to execute the instruction for
            variables: the variable storage instance

        Returns:
            ``True`` if execution must continue, ``False`` if it must be
            interrupted
        """
        self.compute_locals(host_name, variables)
        if self.evaluate_condition(host_name, variables):
            rv = self.execute_action(host_name, variables)
            if not rv:
                self._display.vvvvv(
                    "%s : action %s returned False, stopping"
                    % (host_name, self._action)
                )
        else:
            rv = True
        return rv

    def evaluate_condition(self, host_name, variables):
        """Evaluate the condition for an instruction's execution.

        Args:
            host_name: the name of the host to execute the instruction for
            variables: the variable storage instance

        Returns:
            ``True`` if there is no conditional clause for this instruction, or
            if there is one and it evaluated to a truthy value; ``False``
            otherwise.
        """
        if self._condition is None:
            return True
        t = self._templar
        template = "%s%s%s" % (
            t.environment.variable_start_string,
            self._condition,
            t.environment.variable_end_string,
        )
        rv = boolean(t.template(template, disable_lookups=False))
        self._display.vvvvv(
            "host %s, action %s, condition %s evaluating to %s"
            % (host_name, self._action, repr(self._condition), repr(rv))
        )
        return rv

    def compute_locals(self, host_name, variables):
        """Compute local variables.

        This method iterates through all local variable definitions and runs
        them through the templar.

        Args:
            host_name: the name of the host the instruction is being executed for
            variables: the variable storage instance
        """
        self._templar.available_variables = variables
        for key, value in self._vars.items():
            result = self._templar.template(value)
            variables[key] = result
            self._display.vvvv("- set local variable %s to %s" % (key, result))

    def evaluate_loop(self, host_name, variables):
        """Evaluate the values to iterate over when a ``loop`` is defined.

        Args:
            host_name: the name of the host to execute the instruction for
            variables: the variable storage instance

        Returns:
            the list of items to iterate over
        """
        self._display.vvvvv(
            "host %s, action %s, evaluating loop template %s"
            % (host_name, self._action, repr(self._loop))
        )
        self._templar.available_variables = variables
        value = self._templar.template(self._loop, disable_lookups=False)
        if not isinstance(value, list):
            raise AnsibleRuntimeError(
                "template '%s' did not evaluate to a list" % (self._loop,)
            )
        return value

    def get_templated_group(self, variables, may_be_template, name, must_exist=False):
        """Extract a group name from its source, optionally ensure it exists, \
            then return it.

        Args:
            variables: the variable storage instance
            may_be_template: a flag that indicates whether the name should be \
                processed with the templar.
            name: the name or its template
            must_exist: a flag that, if ``True``, will cause an exception to \
                be raised if the group does not exist.

        Returns:
            the name of the group
        """
        if may_be_template:
            self._templar.available_variables = variables
            real_name = self._templar.template(name)
            if not isinstance(name, string_types):
                raise AnsibleRuntimeError(
                    "%s: '%s' did not coalesce into a string" % (self._action, name)
                )
            real_name = real_name.strip()
            if C.INVALID_VARIABLE_NAMES.findall(real_name):
                raise AnsibleRuntimeError(
                    "%s: '%s' is not a valid group name" % (self._action, real_name)
                )
        else:
            real_name = name
        if must_exist and real_name not in self._inventory.groups:
            raise AnsibleRuntimeError(
                "%s: group '%s' does not exist" % (self._action, real_name)
            )
        return real_name

    @abc.abstractmethod
    def execute_action(self, host_name, variables):
        """Execute the instruction.

        This method must be overridden to implement the actual action of the
        instruction.

        Args:
            host_name: the name of the host to execute the instruction for
            merged_vars: the variable cache, with local script variables \
                taking precedence over host facts.
            host_vars: the host's facts, as a mapping
            script_vars: the current script variables, as a mapping

        Return:
            ``True`` if the script's execution should continue, ``False`` if
            it should be interrupted.
        """
        raise NotImplementedError


class RciCreateGroup(RcInstruction):
    """``create_group`` instruction implementation."""

    def __init__(self, inventory, templar, display):
        super().__init__(inventory, templar, display, "create_group")
        self._group_mbt = None
        self._group_name = None
        self._parent_mbt = None
        self._parent_name = None
        self._add_host = None

    def repr_instruction_only(self):
        output = "%s(group=%s" % (self._action, repr(self._group_name))
        if self._parent_name is not None:
            output += ",parent=" + repr(self._parent_name)
        output += ",add_host=" + repr(self._add_host) + ")"
        return output

    def parse_action(self, record):
        assert self._group_mbt is None and self._group_name is None
        assert self._parent_mbt is None and self._parent_name is None
        assert self._add_host is None
        self._add_host = record.get("add_host", False)
        self._group_mbt, self._group_name = self.parse_group_name(record, "group")
        if "parent" in record:
            self._parent_mbt, self._parent_name = self.parse_group_name(
                record, "parent"
            )

    def execute_action(self, host_name, variables):
        assert not (
            self._group_mbt is None
            or self._group_name is None
            or self._add_host is None
        )
        if self._parent_name is not None:
            parent = self.get_templated_group(
                variables, self._parent_mbt, self._parent_name, must_exist=True
            )
        name = self.get_templated_group(variables, self._group_mbt, self._group_name)
        self._inventory.add_group(name)
        self._display.vvv("- created group %s" % (name,))
        if self._parent_name is not None:
            self._inventory.add_child(parent, name)
            self._display.vvv("- added group %s to %s" % (name, parent))
        if self._add_host:
            self._inventory.add_child(name, host_name)
            self._display.vvv("- added host %s to %s" % (host_name, name))
        return True


class RciAddHost(RcInstruction):
    """``add_host`` instruction implementation."""

    def __init__(self, inventory, templar, display):
        super().__init__(inventory, templar, display, "add_host")
        self._may_be_template = None
        self._group = None

    def repr_instruction_only(self):
        return "%s(group=%s)" % (self._action, repr(self._group))

    def parse_action(self, record):
        assert self._may_be_template is None and self._group is None
        self._may_be_template, self._group = self.parse_group_name(record, "group")

    def execute_action(self, host_name, variables):
        assert not (self._may_be_template is None or self._group is None)
        name = self.get_templated_group(
            variables, self._may_be_template, self._group, must_exist=True
        )
        self._inventory.add_child(name, host_name)
        self._display.vvv("- added host %s to %s" % (host_name, name))
        return True


class RciAddChild(RcInstruction):
    """``add_child`` instruction implementation."""

    def __init__(self, inventory, templar, display):
        super().__init__(inventory, templar, display, "add_child")
        self._group_mbt = None
        self._group_name = None
        self._child_mbt = None
        self._child_name = None

    def repr_instruction_only(self):
        return "%s(group=%s, child=%s)" % (
            self._action,
            repr(self._group_name),
            repr(self._child_name),
        )

    def parse_action(self, record):
        assert self._group_mbt is None and self._group_name is None
        assert self._child_mbt is None and self._child_name is None
        self._group_mbt, self._group_name = self.parse_group_name(record, "group")
        self._child_mbt, self._child_name = self.parse_group_name(record, "child")

    def execute_action(self, host_name, variables):
        assert not (self._group_mbt is None or self._group_name is None)
        assert not (self._child_mbt is None or self._child_name is None)
        group = self.get_templated_group(
            variables, self._group_mbt, self._group_name, must_exist=True
        )
        child = self.get_templated_group(
            variables, self._child_mbt, self._child_name, must_exist=True
        )
        self._inventory.add_child(group, child)
        self._display.vvv("- added group %s to %s" % (child, group))
        return True


class RciSetVarOrFact(RcInstruction):
    """Implementation of the ``set_fact`` and ``set_var`` instructions."""

    def __init__(self, inventory, templar, display, is_fact):
        action = "set_" + ("fact" if is_fact else "var")
        super().__init__(inventory, templar, display, action)
        self._is_fact = is_fact
        self._var_name = None
        self._name_may_be_template = None
        self._var_value = None

    def repr_instruction_only(self):
        return "%s(name=%s, value=%s)" % (
            self._action,
            repr(self._var_name),
            repr(self._var_value),
        )

    def parse_action(self, record):
        assert (
            self._var_name is None
            and self._name_may_be_template is None
            and self._var_value is None
        )
        if "name" not in record:
            raise AnsibleParserError("%s: missing 'name' field" % (self._action,))
        name = record["name"]
        if not isinstance(name, string_types):
            raise AnsibleParserError("%s: 'name' must be a string" % (self._action,))
        if "value" not in record:
            raise AnsibleParserError("%s: missing 'value' field" % (self._action,))
        nmbt = self._templar.is_possibly_template(name)
        if not (nmbt or isidentifier(name)):
            raise AnsibleParserError(
                "%s: '%s' is not a valid variable name" % (self._action, name)
            )
        self._name_may_be_template = nmbt
        self._var_name = name
        self._var_value = record["value"]

    def execute_action(self, host_name, variables):
        assert not (
            self._var_name is None
            or self._name_may_be_template is None
            or self._var_value is None
        )
        self._templar.available_variables = variables
        if self._name_may_be_template:
            name = self._templar.template(self._var_name)
            if not isinstance(name, string_types):
                raise AnsibleRuntimeError(
                    "%s: '%s' did not coalesce into a string"
                    % (self._action, self._var_name)
                )
            if not isidentifier(name):
                raise AnsibleRuntimeError(
                    "%s: '%s' is not a valid variable name" % (self._action, name)
                )
        else:
            name = self._var_name
        value = self._templar.template(self._var_value)
        if self._is_fact:
            self._inventory.set_variable(host_name, name, value)
            variables._set_host_var(name, value)
        else:
            variables[name] = value
        self._display.vvv(
            "- set %s %s to %s"
            % ("fact" if self._is_fact else "var", name, repr(value))
        )
        return True


class RciStop(RcInstruction):
    """``stop`` instruction implementation."""

    def __init__(self, inventory, templar, display):
        super().__init__(inventory, templar, display, "stop")

    def parse_action(self, record):
        pass

    def execute_action(self, host_name, variables):
        self._display.vvv("- stopped execution")
        return False


class RciFail(RcInstruction):
    """``fail`` instruction implementation."""

    def __init__(self, inventory, templar, display):
        super().__init__(inventory, templar, display, "fail")
        self._message = None

    def repr_instruction_only(self):
        if self._message is None:
            return "%s()" % (self._action,)
        else:
            return "%s(%s)" % (self._action, self._message)

    def parse_action(self, record):
        self._message = record.get("msg", None)

    def execute_action(self, host_name, variables):
        if self._message is None:
            message = "fail requested (%s)" % (host_name,)
        else:
            self._templar.available_variables = variables
            message = self._templar.template(self._message)
        self._display.vvv("- failed with message %s" % (message,))
        raise AnsibleRuntimeError(message)


class RciBlock(RcInstruction):
    """``block`` instruction implementation."""

    def __init__(self, inventory, templar, display):
        super().__init__(inventory, templar, display, "block")
        self._block = None
        self._rescue = None
        self._always = None

    def repr_instruction_only(self):
        return "%s(block=%s, rescue=%s, always=%s)" % (
            self._action,
            repr(self._block),
            repr(self._rescue),
            repr(self._always),
        )

    def dump_instruction(self):
        output = ["%s(...):" % (self._action,)]
        self.dump_section(output, "block", self._block)
        self.dump_section(output, "rescue", self._rescue)
        self.dump_section(output, "always", self._always)
        return output

    def dump_section(self, output, section_name, section_contents):
        """Dump one of the sections.

        This method is used to create the dump that corresponds to one of the
        ``block``, ``rescue`` or ``always`` lists of instructions.

        Args:
            output: a list of strings to append to
            block_name: the name of the section being dumped
            block_contents: the list of instructions in this section
        """
        if not section_contents:
            return
        output.append("  " + section_name + ":")
        for pos, instr in enumerate(section_contents):
            if pos != 0:
                output.append("")
            output.extend("    " + s for s in instr.dump())

    def parse_action(self, record):
        assert self._block is None and self._rescue is None and self._always is None
        if "block" not in record:
            raise AnsibleParserError("%s: missing 'block' field" % (self._action,))
        self._block = self.parse_block(record, "block")
        if "rescue" in record:
            self._rescue = self.parse_block(record, "rescue")
        else:
            self._rescue = []
        if "always" in record:
            self._always = self.parse_block(record, "always")
        else:
            self._always = []

    def parse_block(self, record, key):
        """Parse the contents of one of the instruction lists.

        This method will extract the instructions for one of the ``block``,
        ``rescue`` and ``always`` sections. The corresponding key must exist
        in the YAML data when the method is called. It will ensure that it is
        a list before reading the instructions it contains.

        Args:
            record: the record of the ``block`` instruction
            key: the section to read (``block``, ``rescue`` or ``always``)

        Returns:
            the list of instructions in the section.
        """
        if not isinstance(record[key], list):
            raise AnsibleParserError(
                "%s: '%s' field must contain a list of instructions"
                % (self._action, key)
            )
        instructions = []
        for record in record[key]:
            instructions.append(
                parse_instruction(self._inventory, self._templar, self._display, record)
            )
        return instructions

    def execute_action(self, host_name, variables):
        assert not (self._block is None or self._rescue is None or self._always is None)
        try:
            try:
                self._display.vvv("- running 'block' instructions")
                return self.run_section(self._block, host_name, variables)
            except AnsibleError as e:
                if not self._rescue:
                    self._display.vvv("- block failed")
                    raise
                self._display.vvv("- block failed, running 'rescue' instructions")
                variables["reconstructed_error"] = str(e)
                return self.run_section(self._rescue, host_name, variables)
        finally:
            self._display.vvv("- block exited, running 'always' instructions")
            self.run_section(self._always, host_name, variables)

    def run_section(self, section, host_name, variables):
        """Execute a single section.

        This method executes the sequence of instructions in a single section.

        Args:
            section: the list of instructions
            host_name: the name of the host being processed
            variables: the variable storage area

        Returns:
            ``True`` if the script's execution should continue, ``False`` if it
            should be interrupted
        """
        for instruction in section:
            if not instruction.run_for(host_name, variables):
                return False
        return True


INSTRUCTIONS = {
    "add_child": RciAddChild,
    "add_host": RciAddHost,
    "block": RciBlock,
    "create_group": RciCreateGroup,
    "fail": RciFail,
    "set_fact": lambda i, t, d: RciSetVarOrFact(i, t, d, True),
    "set_var": lambda i, t, d: RciSetVarOrFact(i, t, d, False),
    "stop": RciStop,
}


def parse_instruction(inventory, templar, display, record):
    action = record["action"]
    if action not in INSTRUCTIONS:
        raise AnsibleParserError("Unknown action '%s'" % (action,))
    instruction = INSTRUCTIONS[action](inventory, templar, display)
    instruction.parse(record)
    return instruction


class InventoryModule(BaseInventoryPlugin):
    """Constructs groups based on lists of instructions."""

    NAME = "reconstructed"

    def verify_file(self, path):
        return super().verify_file(path) and path.endswith((".yaml", ".yml"))

    def parse(self, inventory, loader, path, cache=True):
        super().parse(inventory, loader, path, cache)
        self._read_config_data(path)
        # Read the program
        instr_src = self.get_option("instructions")
        instructions = []
        for record in instr_src:
            instructions.append(
                parse_instruction(self.inventory, self.templar, self.display, record)
            )
        self.dump_program(instructions)
        # Execute it for each host
        for host in inventory.hosts:
            self.display.vvv("executing reconstructed script for %s" % (host,))
            try:
                self.exec_for_host(host, instructions)
            except AnsibleError as e:
                if self.get_option("strictness") == "full":
                    raise
                self.display.warning(
                    "reconstructed - error on host %s: %s" % (host, repr(e))
                )

    def exec_for_host(self, host, instructions):
        """Execute the program for a single host.

        This method initialises a variable storage instance from the host's
        variables then runs the instructions.

        Args:
            host: the name of the host to execute for
            instructions: the list of instructions to execute
        """
        host_vars = self.inventory.get_host(host).get_vars()
        variables = VariableStorage(host_vars)
        for instruction in instructions:
            if not instruction.run_for(host, variables):
                return

    def dump_program(self, instructions):
        """Dump the whole program to the log, depending on verbosity level.

        This method will dump the program to the log. If verbosity is at level
        3, the dump will be written using `repr`. If it is 4 or higher, it will
        be dumped in a much more readable, albeit longer,  form.

        Args:
            instructions: the list of instructions in the program
        """
        if self.display.verbosity < 4:
            if self.display.verbosity == 3:
                self.display.vvv("parsed program: " + repr(instructions))
            return
        output = []
        for pos, instr in enumerate(instructions):
            if pos:
                output.append("")
            output.extend(instr.dump())
        self.display.vvvv("parsed program:\n\n" + "\n".join("  " + s for s in output))
