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
          be written; by default the C(item) variable will be used.
        - The C(when) field, if present, must contain a Jinja expression
          representing a condition which will be checked before the instruction
          is executed.
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
          or C(always) will go out of scope once the block finishes executing.
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


class RcInstruction:
    """An instruction that can be executed by the plugin."""

    COMMON_FIELDS = ("when", "loop", "loop_var", "action")
    DEFAULT_LOOP_VAR = "item"

    def __init__(self, inventory, templar, display, action, allowed_fields=()):
        self._inventory = inventory
        self._templar = templar
        self._display = display
        self._condition = None
        self._loop = None
        self._loop_var = None
        self._action = action
        self._allowed_fields = set(allowed_fields)
        self._allowed_fields.update(RcInstruction.COMMON_FIELDS)

    def __repr__(self):
        flow = []
        if self._condition is not None:
            flow.append(
                "when=%s"
                % (
                    repr(
                        self._condition,
                    )
                )
            )
        if self._loop is not None:
            flow.append(
                "loop=%s, loop_var=%s" % (repr(self._loop), repr(self._loop_var))
            )
        if flow:
            output = "{%s}" % (", ".join(flow),)
        else:
            output = ""
        output += self.repr_instruction_only()
        return output

    def repr_instruction_only(self):
        return "%s()" % (self._action,)

    def dump(self):
        output = []
        if self._condition is not None:
            output.append("when: %s" % (repr(self._condition),))
        if self._loop is not None:
            output.append("loop[%s]: %s" % (self._loop_var, repr(self._loop)))
        output.extend(self.dump_instruction())
        return output

    def dump_instruction(self):
        return [self.repr_instruction_only()]

    def parse(self, record):
        assert "action" in record and record["action"] == self._action
        # Ensure there are no unsupported fields
        extra_fields = set(record.keys()).difference(self._allowed_fields)
        if extra_fields:
            raise AnsibleParserError(
                "%s: unsupported fields: %s" % (self._action, ", ".join(extra_fields))
            )
        # Extract the condition
        if "when" in record:
            if not isinstance(record["when"], string_types):
                raise AnsibleParserError(
                    "%s: 'when' clause is not a string" % (self._action,)
                )
            self._condition = record["when"]
        # Extract the loop data and configuration
        if "loop" in record:
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
        elif "loop_var" in record:
            raise AnsibleParserError(
                "%s: 'loop_var' clause found without 'loop'" % (self._action,)
            )
        # Process action-specific fields
        self.parse_action(record)

    def parse_group_name(self, record, name):
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

    def parse_action(self, record):
        raise NotImplementedError

    def run_for(self, host_name, host_vars, script_vars):
        merged_vars = host_vars.copy()
        merged_vars.update(script_vars)
        if self._loop is None:
            self._display.vvvv("%s : running action %s" % (host_name, self._action))
            return self.run_once(host_name, merged_vars, host_vars, script_vars)
        loop_values = self.evaluate_loop(host_name, merged_vars)
        script_vars = script_vars.copy()
        for value in loop_values:
            self._display.vvvv(
                "%s : running action %s for item %s"
                % (host_name, self._action, repr(value))
            )
            merged_vars[self._loop_var] = value
            script_vars[self._loop_var] = value
            if not self.run_once(host_name, merged_vars, host_vars, script_vars):
                return False
        return True

    def run_once(self, host_name, merged_vars, host_vars, script_vars):
        if self.evaluate_condition(host_name, merged_vars):
            rv = self.execute_action(host_name, merged_vars, host_vars, script_vars)
            if not rv:
                self._display.vvvvv(
                    "%s : action %s returned False, stopping"
                    % (host_name, self._action)
                )
        else:
            rv = True
        return rv

    def evaluate_condition(self, host_name, variables):
        if self._condition is None:
            return True
        t = self._templar
        t.available_variables = variables
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

    def evaluate_loop(self, host_name, variables):
        if isinstance(self._loop, list):
            return self._loop
        assert isinstance(self._loop, string_types)
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

    def execute_action(self, host_name, merged_vars, host_vars, script_vars):
        raise NotImplementedError

    def get_templated_group(self, variables, may_be_template, name, must_exist=False):
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


class RciCreateGroup(RcInstruction):
    def __init__(self, inventory, templar, display):
        super().__init__(
            inventory, templar, display, "create_group", ("group", "parent", "add_host")
        )
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

    def execute_action(self, host_name, merged_vars, host_vars, script_vars):
        assert not (
            self._group_mbt is None
            or self._group_name is None
            or self._add_host is None
        )
        if self._parent_name is not None:
            parent = self.get_templated_group(
                merged_vars, self._parent_mbt, self._parent_name, must_exist=True
            )
        name = self.get_templated_group(merged_vars, self._group_mbt, self._group_name)
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
    def __init__(self, inventory, templar, display):
        super().__init__(inventory, templar, display, "add_host", ("group",))
        self._may_be_template = None
        self._group = None

    def repr_instruction_only(self):
        return "%s(group=%s)" % (self._action, repr(self._group))

    def parse_action(self, record):
        assert self._may_be_template is None and self._group is None
        self._may_be_template, self._group = self.parse_group_name(record, "group")

    def execute_action(self, host_name, merged_vars, host_vars, script_vars):
        assert not (self._may_be_template is None or self._group is None)
        name = self.get_templated_group(
            merged_vars, self._may_be_template, self._group, must_exist=True
        )
        self._inventory.add_child(name, host_name)
        self._display.vvv("- added host %s to %s" % (host_name, name))
        return True


class RciAddChild(RcInstruction):
    def __init__(self, inventory, templar, display):
        super().__init__(inventory, templar, display, "add_child", ("group", "child"))
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

    def execute_action(self, host_name, merged_vars, host_vars, script_vars):
        assert not (self._group_mbt is None or self._group_name is None)
        assert not (self._child_mbt is None or self._child_name is None)
        group = self.get_templated_group(
            merged_vars, self._group_mbt, self._group_name, must_exist=True
        )
        child = self.get_templated_group(
            merged_vars, self._child_mbt, self._child_name, must_exist=True
        )
        self._inventory.add_child(group, child)
        self._display.vvv("- added group %s to %s" % (child, group))
        return True


class RciSetVarOrFact(RcInstruction):
    def __init__(self, inventory, templar, display, is_fact):
        action = "set_" + ("fact" if is_fact else "var")
        super().__init__(inventory, templar, display, action, ("name", "value"))
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

    def execute_action(self, host_name, merged_vars, host_vars, script_vars):
        assert not (
            self._var_name is None
            or self._name_may_be_template is None
            or self._var_value is None
        )
        self._templar.available_variables = merged_vars
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
        merged_vars[name] = value
        if self._is_fact:
            self._inventory.set_variable(host_name, name, value)
            host_vars[name] = value
        else:
            script_vars[name] = value
        self._display.vvv(
            "- set %s %s to %s"
            % ("fact" if self._is_fact else "var", name, repr(value))
        )
        return True


class RciStop(RcInstruction):
    def __init__(self, inventory, templar, display):
        super().__init__(inventory, templar, display, "stop")

    def parse_action(self, record):
        pass

    def execute_action(self, host_name, merged_vars, host_vars, script_vars):
        self._display.vvv("- stopped execution")
        return False


class RciFail(RcInstruction):
    def __init__(self, inventory, templar, display):
        super().__init__(inventory, templar, display, "fail", ("msg",))
        self._message = None

    def repr_instruction_only(self):
        if self._message is None:
            return "%s()" % (self._action,)
        else:
            return "%s(%s)" % (self._action, self._message)

    def parse_action(self, record):
        self._message = record.get("msg", None)

    def execute_action(self, host_name, merged_vars, host_vars, script_vars):
        if self._message is None:
            message = "fail requested (%s)" % (host_name,)
        else:
            self._templar.available_variables = merged_vars
            message = self._templar.template(self._message)
        self._display.vvv("- failed with message %s" % (message,))
        raise AnsibleRuntimeError(message)


class RciBlock(RcInstruction):
    def __init__(self, inventory, templar, display):
        super().__init__(
            inventory,
            templar,
            display,
            "block",
            ("block", "rescue", "always", "locals"),
        )
        self._block = None
        self._rescue = None
        self._always = None
        self._locals = None

    def repr_instruction_only(self):
        return "%s(block=%s, rescue=%s, always=%s, locals=%s)" % (
            self._action,
            repr(self._block),
            repr(self._rescue),
            repr(self._always),
            repr(self._locals),
        )

    def dump_instruction(self):
        output = ["%s(...):" % (self._action,)]
        self.dump_block(output, "block", self._block)
        self.dump_block(output, "rescue", self._rescue)
        self.dump_block(output, "always", self._always)
        if self._locals:
            output.append("  locals:")
            for k, v in self._locals.items():
                output.append("    " + repr(k) + "=" + repr(v))
        return output

    def dump_block(self, output, block_name, block_contents):
        if not block_contents:
            return
        output.append("  " + block_name + ":")
        for pos, instr in enumerate(block_contents):
            if pos != 0:
                output.append("")
            output.extend("    " + s for s in instr.dump())

    def parse_action(self, record):
        assert (
            self._block is None
            and self._rescue is None
            and self._always is None
            and self._locals is None
        )
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
        if "locals" in record:
            if not isinstance(record["locals"], dict):
                raise AnsibleParserError(
                    "%s: 'locals' should be a dictionnary" % (self._action,)
                )
            for k, v in record["locals"].items():
                if not isinstance(k, string_types):
                    raise AnsibleParserError(
                        "%s: locals identifiers must be strings" % (self._action,)
                    )
                if not isidentifier(k):
                    raise AnsibleParserError(
                        "%s: '%s' is not a valid identifier" % (self._action, k)
                    )
            self._locals = record["locals"]
        else:
            self._locals = {}

    def parse_block(self, record, key):
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

    def execute_action(self, host_name, merged_vars, host_vars, script_vars):
        assert not (
            self._block is None
            or self._rescue is None
            or self._always is None
            or self._locals is None
        )
        merged_vars = merged_vars.copy()
        script_vars = script_vars.copy()
        self._templar.available_variables = merged_vars
        for key, value in self._locals.items():
            result = self._templar.template(value)
            script_vars[key] = result
            merged_vars[key] = result
            self._display.vvv("- set block-local %s to %s" % (key, result))
        try:
            try:
                self._display.vvv("- running 'block' instructions")
                return self.run_block(
                    self._block, host_name, merged_vars, host_vars, script_vars
                )
            except AnsibleError as e:
                if not self._rescue:
                    self._display.vvv("- block failed")
                    raise
                self._display.vvv("- block failed, running 'rescue' instructions")
                script_vars["reconstructed_error"] = str(e)
                merged_vars["reconstructed_error"] = str(e)
                return self.run_block(
                    self._rescue, host_name, merged_vars, host_vars, script_vars
                )
        finally:
            self._display.vvv("- block exited, running 'always' instructions")
            self.run_block(self._always, host_name, merged_vars, host_vars, script_vars)

    def run_block(self, block, host_name, merged_vars, host_vars, script_vars):
        for instruction in block:
            if not instruction.run_for(host_name, host_vars, script_vars):
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
        instr_src = self.get_option("instructions")
        instructions = []
        for record in instr_src:
            instructions.append(
                parse_instruction(self.inventory, self.templar, self.display, record)
            )
        self.dump_program(instructions)
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
        host_vars = self.inventory.get_host(host).get_vars()
        script_vars = {}
        for instruction in instructions:
            if not instruction.run_for(host, host_vars, script_vars):
                return

    def dump_program(self, instructions):
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
