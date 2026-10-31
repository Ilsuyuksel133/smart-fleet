"""UI tests for the Streamlit dashboard, run against the running stack."""

import re

from playwright.sync_api import Page, expect


def test_fleet_page_loads(page: Page):
    page.goto("/")
    expect(page.get_by_role("heading", name="Smart Fleet Monitor")).to_be_visible()
    expect(page.get_by_role("heading", name="Vehicles")).to_be_visible()


def test_navigate_to_incidents(page: Page):
    page.goto("/")
    page.get_by_role("link", name="Incidents").click()
    expect(page.get_by_role("heading", name="Incidents")).to_be_visible()


def test_incident_report_is_shown(page: Page):
    page.goto("/Incidents")
    expect(page.get_by_text("Root cause", exact=True)).to_be_visible()
    expect(page.get_by_text("Suggested actions", exact=True)).to_be_visible()
    expect(page.get_by_text("Evidence", exact=True)).to_be_visible()


def test_manual_investigation(page: Page):
    page.goto("/Incidents")
    page.get_by_text("Start an investigation manually").click()
    page.get_by_role("button", name="Investigate").click()

    started = page.get_by_text(re.compile(r"Investigation #\d+ queued"))
    already_running = page.get_by_text(re.compile(r"^Not started"))
    expect(started.or_(already_running)).to_be_visible()
    expect(page.get_by_text("Cannot reach the agent")).not_to_be_visible()
