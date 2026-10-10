"""Umbrella package holding one subpackage per runnable agent.

Deliberately left empty: importing a subpackage runs this file first, so any
import added here would be paid by every subpackage, even the ones that do not
need it. Each agent exposes its own API from its own __init__.py instead.
"""
