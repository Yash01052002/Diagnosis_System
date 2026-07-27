"""Unit tests for schema validation and pagination maths."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.common import Page, PaginationParams
from app.schemas.user import UserCreate


class TestPasswordPolicy:
    @pytest.mark.parametrize(
        ("password", "expected"),
        [
            ("Str0ng!Passw0rd", None),
            ("short1!A", "at least"),
            ("alllowercase1!", "uppercase"),
            ("ALLUPPERCASE1!", "lowercase"),
            ("NoDigitsHere!!", "digit"),
            ("NoSpecialChar1", "special"),
        ],
    )
    def test_policy(self, password: str, expected: str | None) -> None:
        if expected is None:
            assert UserCreate(email="a@b.com", password=password).password == password
            return
        with pytest.raises(PydanticValidationError, match=expected):
            UserCreate(email="a@b.com", password=password)

    def test_invalid_email_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            UserCreate(email="not-an-email", password="Str0ng!Passw0rd")


class TestPagination:
    def test_offset_and_limit(self) -> None:
        params = PaginationParams(page=3, page_size=25)

        assert params.offset == 50
        assert params.limit == 25

    @pytest.mark.parametrize(
        ("total", "page_size", "expected_pages"),
        [(0, 20, 0), (1, 20, 1), (20, 20, 1), (21, 20, 2), (100, 30, 4)],
    )
    def test_page_count(self, total: int, page_size: int, expected_pages: int) -> None:
        page = Page.create([], total, PaginationParams(page=1, page_size=page_size))

        assert page.pages == expected_pages
        assert page.total == total

    @pytest.mark.parametrize("page_size", [0, 201])
    def test_page_size_bounds(self, page_size: int) -> None:
        with pytest.raises(PydanticValidationError):
            PaginationParams(page=1, page_size=page_size)
