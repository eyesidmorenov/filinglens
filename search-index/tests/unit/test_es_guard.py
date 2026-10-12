"""Tests never touch production indices or aliases."""

import pytest
from es_helpers import delete_test_indices, guard_test_name


class RecordingClient:
    """Minimal fake client: lists what 'exists' and records deletions."""

    def __init__(self, existing):
        self.existing = existing
        self.deleted = []
        self.indices = self

    def get(self, index, allow_no_indices):
        return {name: {} for name in self.existing}

    def delete(self, index):
        self.deleted.append(index)


def test_names_without_the_test_prefix_are_refused():
    with pytest.raises(RuntimeError, match="filinglens-chunks"):
        guard_test_name("filinglens-chunks")


def test_cleanup_refuses_a_production_alias_before_touching_anything():
    client = RecordingClient(["filinglens-chunks"])

    with pytest.raises(RuntimeError):
        delete_test_indices(client, "filinglens-chunks")

    assert client.deleted == []


def test_cleanup_deletes_only_names_that_carry_the_test_prefix():
    client = RecordingClient(["test_filinglens_ab12cd34", "filinglens-chunks"])

    with pytest.raises(RuntimeError):
        delete_test_indices(client, "test_filinglens_ab12cd34")

    assert client.deleted == ["test_filinglens_ab12cd34"]
