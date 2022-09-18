"""Tests for the variable storage / cache."""
import pytest

from . import reconstructed


class TestBasics:
    """Test basic access to the store."""

    @pytest.fixture
    def host_vars(self):
        """A set of fake host vars to use."""
        return {
            "var1": "value1",
            "var2": "value2",
        }

    @pytest.fixture
    def store(self, host_vars):
        """A store initialized with the host variables above."""
        return reconstructed.VariableStorage(host_vars)

    def test_init(self, host_vars, store):
        """Reference to host vars is copied, cache is initialized, stack is empty."""
        assert store._host_vars is host_vars
        assert store._cache == host_vars
        assert store._cache is not host_vars
        assert len(store._script_vars) == 0
        assert len(store._script_stack) == 0

    def test_read_hostvar(self, host_vars, store):
        """Host vars can be read from the store."""
        for k, v in host_vars.items():
            assert store[k] == host_vars[k]

    def test_del_hostvars(self, host_vars, store):
        """Host variables cannot be deleted."""
        for k in host_vars.keys():
            with pytest.raises(KeyError):
                del store[k]
            assert k in store._host_vars
            assert k in store._cache
            assert store[k] == host_vars[k]

    def test_write_local(self, host_vars, store):
        """Variables can be written and read back."""
        k, v = "local", "valuel"
        assert k not in store
        store[k] = v
        assert k in store
        assert store[k] == v
        assert k not in host_vars
        assert k in store._script_vars
        assert store._script_vars[k] == v
        assert k in store._cache
        assert store._cache[k] == v

    def test_del_local(self, host_vars, store):
        """Local variables can be deleted."""
        k, v = "local", "valuel"
        assert k not in store
        store[k] = v
        del store[k]
        assert k not in store
        assert k not in host_vars
        assert k not in store._script_vars
        assert k not in store._cache

    def test_local_hides_hostvar(self, host_vars, store):
        """Local variables can hide host variables with the same name."""
        k = tuple(host_vars.keys())[0]
        initial = host_vars[k]
        v = initial + "nope"
        store[k] = v
        assert k in store
        assert store[k] == v
        assert host_vars[k] == initial
        assert k in store._script_vars
        assert store._script_vars[k] == v
        assert k in store._cache
        assert store._cache[k] == v

    def test_del_unhides_hostvar(self, host_vars, store):
        """Deleting a local that hides a host vars makes the host var visible again."""
        k = tuple(host_vars.keys())[0]
        initial = host_vars[k]
        v = initial + "nope"
        store[k] = v
        del store[k]
        assert k in store
        assert store[k] == initial
        assert host_vars[k] == initial
        assert k not in store._script_vars
        assert k in store._cache
        assert store._cache[k] == initial


class TestIterators:
    """Tests for the various iterator methods."""

    @pytest.fixture
    def host_vars(self):
        """A set of fake host vars to use."""
        return {
            "var1": "value1",
            "var2": "value2",
        }

    @pytest.fixture
    def local_vars(self, host_vars):
        """A set of local vars, one of which overrides a host var."""
        k = tuple(host_vars.keys())[0]
        return {
            k: "not " + host_vars[k],
            "varl": "valuel",
        }

    @pytest.fixture
    def store(self, host_vars, local_vars):
        """A store initialized with both host variables and locals."""
        store = reconstructed.VariableStorage(host_vars)
        for k, v in local_vars.items():
            store[k] = v
        return store

    def test_keys(self, host_vars, local_vars, store):
        """A store's keys are the union of its host and local variable names."""
        expected = set(host_vars.keys()) | set(local_vars.keys())
        actual = set(store.keys())
        assert expected == actual

    def test_values(self, host_vars, local_vars, store):
        """A store's values correspond to the ones in host and local variables, \
                with the latter taking precedence."""
        expected = dict(host_vars)
        expected.update(local_vars)
        assert tuple(expected.values()) == tuple(store.values())

    def test_items(self, host_vars, local_vars, store):
        """A store's items correspond to the ones in host and local variables, \
                with the latter taking precedence."""
        expected = dict(host_vars)
        expected.update(local_vars)
        assert tuple(expected.items()) == tuple(store.items())

    def test_iter(self, host_vars, local_vars, store):
        """Iterating over a store is equivalent to getting its keys."""
        expected = set(host_vars.keys()) | set(local_vars.keys())
        actual = set(k for k in store)
        assert expected == actual


class TestStack:
    """Tests for the stack features of the variable storage class."""

    @pytest.fixture
    def host_vars(self):
        """A set of fake host vars to use."""
        return {
            "var1": ["value1"],
        }

    @pytest.fixture
    def local_vars(self):
        """A set of fake local variables."""
        return {
            "varl1": ["valuel1"],
        }

    @pytest.fixture
    def store(self, host_vars, local_vars):
        """A store initialized with both host variables and locals."""
        store = reconstructed.VariableStorage(host_vars)
        for k, v in local_vars.items():
            store[k] = v
        return store

    def test_push_empty(self, store):
        """Test pushing nothing."""
        store._script_stack_push(())
        assert len(store._script_stack) == 1
        assert store._script_stack[0] == {}

    def test_push_missing(self, store):
        """Test pushing a variable that is not defined."""
        v = "nope"
        assert v not in store._script_vars
        assert v not in store._host_vars
        store._script_stack_push((v,))
        assert len(store._script_stack) == 1
        assert store._script_stack[0] == {v: (False, None)}

    def test_push_host(self, store, host_vars):
        """Test pushing a single, existing host var."""
        v = "var1"
        assert v in store._host_vars
        store._script_stack_push((v,))
        assert len(store._script_stack) == 1
        assert store._script_stack[0] == {v: (False, None)}

    def test_push_local(self, store):
        """Test pushing a single, existing local var."""
        v = "varl1"
        assert v in store._script_vars
        store._script_stack_push((v,))
        assert len(store._script_stack) == 1
        assert store._script_stack[0] == {v: (True, store._script_vars[v])}
        assert store._script_stack[0][v][1] is not store._script_vars[v]

    def test_pop_empty(self, store):
        """Test poping an empty stack entry."""
        old_cache = store._cache
        store._script_stack.append({})
        store._script_stack_pop()
        assert len(store._script_stack) == 0
        assert store._cache is old_cache

    def test_pop_missing(self, store):
        """Test poping a variable that is not defined."""
        old_cache = store._cache
        v = "nope"
        assert v not in store._script_vars
        assert v not in store._host_vars
        store._script_stack.append({v: (False, None)})
        store._script_stack_pop()
        assert len(store._script_stack) == 0
        assert store._cache is old_cache

    def test_pop_unchanged_host(self, store):
        """Test poping a host variable that was not overridden."""
        old_cache = store._cache
        v = "var1"
        assert v in store._host_vars
        assert v not in store._script_vars
        store._script_stack.append({v: (False, None)})
        store._script_stack_pop()
        assert len(store._script_stack) == 0
        assert store._cache is old_cache

    def test_pop_overridden_host(self, store):
        """Test poping a host variable that was overridden."""
        old_cache = store._cache
        v_name = "var1"
        v_value = "test"
        assert v_name in store._host_vars
        assert v_name not in store._script_vars
        store._script_stack.append({v_name: (False, None)})
        store._script_vars[v_name] = v_value
        store._cache[v_name] = v_value
        assert store[v_name] == v_value

        store._script_stack_pop()

        assert len(store._script_stack) == 0
        assert store._cache is not old_cache
        assert store._cache[v_name] == store._host_vars[v_name]
        assert v_name not in store._script_vars

    def test_pop_unchanged_local(self, store):
        """Test poping a script variable that was not changed."""
        old_cache = store._cache
        v_name = "varl1"
        assert v_name not in store._host_vars
        assert v_name in store._script_vars
        v_initial = store._script_vars[v_name]
        store._script_stack.append({v_name: (True, v_initial)})

        store._script_stack_pop()

        assert len(store._script_stack) == 0
        assert store._cache is not old_cache
        assert v_name in store._cache
        assert store._cache[v_name] is v_initial
        assert v_name in store._script_vars
        assert store._script_vars[v_name] is v_initial

    def test_pop_modified_local(self, store):
        """Test poping a script variable that was modified."""
        old_cache = store._cache
        v_name = "varl1"
        assert v_name not in store._host_vars
        assert v_name in store._script_vars
        v_initial = store._script_vars[v_name]
        v_new = ["no"]
        store._script_vars[v_name] = v_new
        store._cache[v_name] = v_new
        store._script_stack.append({v_name: (True, v_initial)})

        store._script_stack_pop()

        assert len(store._script_stack) == 0
        assert store._cache is not old_cache
        assert v_name in store._cache
        assert store._cache[v_name] is v_initial
        assert v_name in store._script_vars
        assert store._script_vars[v_name] is v_initial
