"""Shared Textual messages used across multiple tabs/screens."""

from textual.message import Message


class CategoriesChanged(Message):
    """Posted when a category is created or deleted from any tab."""
