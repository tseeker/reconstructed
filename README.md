reconstructed
=============

An Ansible plugin that can generate structured inventories programmatically.

This is a work in progress. I will make this README more useful later, provided
I just don't forget about this whole thing.

A `reconstructed` inventory executes a list of instructions that is read
from the `instructions` YAML field. Each instruction is a table with some
minimal control flow (`when`, `loop` and `run_once` keywords that work mostly
like their playbook cousins), an `action` field that contains the name of the
instruction to execute, and whatever fields are needed for the instruction.

The following actions are supported:

  * `create_group` creates a group. The name of the group must be
    provided using the `group` field, which must be a valid name or a
    Jinja template that evaluates to a valid name. In addition, a
    `parent` field containting the name of a single, existing parent
    group (or a Jinja template generating the name) may be provided.
    Finally, the `add_host` field may be set to a truthy value if the
    current host must be added to the new group.

  * `add_child` adds a child group to another group. The name of the
    group being added must be provided in the `child` entry, while
    the name of the parent must be provided in the `group` entry. Both
    groups must exist. In addition, the names may be specified using
    Jinja templates.

  * `add_host` adds the current inventory host to a group. The name
    of the group must be provided in the `group` entry. The group
    must exist.

  * `fail` causes the computations for the current host to stop with
    an error. The error message may be specified in the `message`
    entry; if present, it will be evaluated using Jinja.

  * `set_fact` and `set_var` create a fact and a local variable,
    respectively. Local variables will only be kept during the execution
    of the script for the current host, while facts will be added to the
    host's data. The `name` entry specifies the name of the fact or
    variable while the `value` entry specifies its value. Both may be
    Jinja templates.

  * `stop` stops processing the list of instructions for the current
    host.

In addition, the `block` can be used to repeat multiple instructions or make
them obey a single conditional. The instruction must include a `block` field,
containing the list of instructions which are part of the block. It may have
a `rescue` field, containing a list of instructions which will be executed on
error, and `always`, which may contain a list of instructions to execute in
all cases.

If the `vars` field is defined on an instruction, it must contain a table of
local variables to define. Their values are computed after the loop variable
is evaluated, but before the condition is. If these variables already existed,
their state will be saved and they will be restored after the instruction is
done executing. This is different from the core Ansible behaviour, which does
not evaluate the `vars` unless they are used.
