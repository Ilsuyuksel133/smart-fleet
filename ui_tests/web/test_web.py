"""UI tests for the React web app (nginx on :8080), run against the running stack.

The smoke test runs first in CI: it creates the vehicle "smoke-test" and a finished
agent report, and the simulator keeps sending readings.
"""

import re

from playwright.sync_api import Page, expect


def test_fleet_page_lists_vehicles(page: Page):
    page.goto("/")
    expect(page.get_by_role("heading", name="Fleet", level=1)).to_be_visible()
    vehicles = page.get_by_role("table", name=re.compile("vehicles", re.IGNORECASE))
    # Every smoke test run adds a vehicle with this name
    expect(vehicles.get_by_role("link", name="smoke-test").first).to_be_visible()
    expect(page.get_by_text("Cannot reach the API")).not_to_be_visible()


def test_vehicle_detail_shows_chart(page: Page):
    page.goto("/")
    page.get_by_role("link", name="smoke-test").first.click()
    expect(page).to_have_url(re.compile(r"/vehicles/\d+$"))
    expect(page.get_by_role("heading", name="smoke-test", level=1)).to_be_visible()
    expect(page.get_by_role("img", name=re.compile("Temperature of the last"))).to_be_visible()


def test_alert_filter_is_kept_in_the_url(page: Page):
    page.goto("/alerts")
    page.get_by_label("Type").select_option("high_temperature")
    expect(page).to_have_url(re.compile(r"type=high_temperature"))
    # The smoke test sent 95 °C, so there is at least one alert of this type
    expect(page.get_by_role("cell", name="high temperature").first).to_be_visible()


def test_incident_report_is_shown(page: Page):
    page.goto("/incidents")
    # Newest finished report (the one from the smoke test, or a later one);
    # an alert may have started another investigation that is still running
    done = page.get_by_role("row").filter(has=page.get_by_text("done", exact=True))
    done.first.get_by_role("link", name=re.compile(r"^#\d+$")).click()
    expect(page).to_have_url(re.compile(r"/incidents/\d+$"))
    expect(page.get_by_role("heading", name="Root cause")).to_be_visible()
    expect(page.get_by_role("heading", name="Evidence")).to_be_visible()


def test_manual_investigation(page: Page):
    page.goto("/incidents")
    page.get_by_role("button", name="Start investigation").click()

    started = page.get_by_text(re.compile(r"Investigation #\d+ queued"))
    already_running = page.get_by_text(re.compile(r"^Not started"))
    expect(started.or_(already_running)).to_be_visible()
    expect(page.get_by_text("Cannot reach the agent")).not_to_be_visible()
