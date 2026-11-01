import re

import pytest

from tests.ui.mock_api import record

pytestmark = pytest.mark.ui

FIELDS = {
    "full_name": "Wanjiku Kamau", "email": "Wanjiku@Example.co.ke", "phone": "0712345678",
    "national_id": "12345678", "password": "a-long-password",
}


def open_site(page, api):
    page.goto(api.url + "/")
    page.wait_for_selector("#welcome:not([hidden]), #search:not([hidden])")


def with_stored_token(page, api, token):
    page.add_init_script(f"sessionStorage.setItem('ngao_token', '{token}')")
    page.goto(api.url + "/")


def signed_in(page, api):
    with_stored_token(page, api, "test-token")
    page.wait_for_selector("#search:not([hidden])")


def start_search(page):
    page.evaluate("document.querySelector('.controls details').open = true")
    page.fill("#lat", "-1.2864")
    page.fill("#lon", "36.8172")
    page.click("#search-coords")


def search_from_nairobi(page):
    start_search(page)
    page.wait_for_function("state.searched === true")


def fill_signup(page):
    page.click("[data-go=signup]")
    for name, value in FIELDS.items():
        page.fill(f"#signup-form [name={name}]", value)


def test_welcome_screen_explains_the_service_and_shows_the_helplines(app_page, api):
    open_site(app_page, api)
    assert app_page.title() == "Ngao"
    assert app_page.locator("h1").inner_text() == "Ngao"
    assert "within 15 km" in app_page.locator(".lede").inner_text()
    helplines = app_page.locator("footer .help").inner_text()
    assert all(number in helplines for number in ("999", "112", "1195", "116"))
    assert app_page.locator(".flag").count() == 2


def test_page_loads_nothing_from_outside_except_fonts(app_page, api):
    open_site(app_page, api)
    hosts = {re.match(r"https?://([^/]+)", url).group(1) for url in app_page.outside_requests}
    assert hosts <= {"fonts.googleapis.com", "fonts.gstatic.com"}


def test_sign_up_then_confirm_then_search_end_to_end(app_page, api):
    open_site(app_page, api)
    fill_signup(app_page)
    app_page.click("#signup-form button[type=submit]")
    app_page.wait_for_selector("#verify:not([hidden])")
    assert app_page.locator("#verify-email").inner_text() == "wanjiku@example.co.ke"
    assert "482913" in app_page.locator("#demo-codes").inner_text()

    app_page.fill("#verify-form [name=email_code]", "482913")
    app_page.fill("#verify-form [name=phone_code]", "107355")
    app_page.click("#verify-form button[type=submit]")
    app_page.wait_for_selector("#search:not([hidden])")
    assert app_page.evaluate("sessionStorage.getItem('ngao_token')") == "test-token"
    assert app_page.locator("#badge").is_visible()

    search_from_nairobi(app_page)
    assert app_page.locator(".record").count() == 5
    assert "5 listed within 15 km" in app_page.locator("#results-sub").inner_text()


def test_signup_sends_the_form_as_typed_and_clears_the_password_after_confirming(app_page, api):
    open_site(app_page, api)
    fill_signup(app_page)
    app_page.click("#signup-form button[type=submit]")
    app_page.wait_for_selector("#verify:not([hidden])")
    sent = api.requests_to("/register")[0]["body"]
    assert sent["national_id"] == "12345678" and sent["phone"] == "0712345678"

    app_page.fill("#verify-form [name=email_code]", "482913")
    app_page.fill("#verify-form [name=phone_code]", "107355")
    app_page.click("#verify-form button[type=submit]")
    app_page.wait_for_selector("#search:not([hidden])")
    assert app_page.evaluate("state.password") == ""


def test_coordinates_travel_in_the_request_body_never_the_url(app_page, api):
    signed_in(app_page, api)
    search_from_nairobi(app_page)
    request = api.requests_to("/nearby")[0]
    assert "?" not in request["path"] and "-1.28" not in request["path"]
    assert request["body"] == {"latitude": -1.2864, "longitude": 36.8172, "radius_km": 15}


def test_privacy_wording_does_not_overpromise(app_page, api):
    signed_in(app_page, api)
    search_from_nairobi(app_page)
    text = app_page.locator("#results-sub").inner_text()
    assert "does not save the location you search from" in text
    assert "not stored" not in text


def test_rings_count_records_per_distance_band(app_page, api):
    signed_in(app_page, api)
    search_from_nairobi(app_page)
    counts = {band: app_page.locator(f"[data-count='{band}']").text_content() for band in ("5", "10", "15")}
    assert counts == {"5": "2", "10": "1", "15": "2"}


def test_choosing_a_band_filters_the_list_and_choosing_it_again_clears_it(app_page, api):
    signed_in(app_page, api)
    search_from_nairobi(app_page)
    app_page.click("#bands button[data-band='10']")
    assert app_page.locator(".record").count() == 1
    assert "Within 7 km" in app_page.locator(".record").inner_text()
    assert app_page.locator("#bands button[data-band='10']").get_attribute("aria-pressed") == "true"
    app_page.click("#bands button[data-band='10']")
    assert app_page.locator(".record").count() == 5


def test_category_filter_is_sent_to_the_server(app_page, api):
    signed_in(app_page, api)
    app_page.select_option("#category", "CHILD_SEXUAL_OFFENCE")
    search_from_nairobi(app_page)
    assert api.requests_to("/nearby")[-1]["body"]["category"] == "CHILD_SEXUAL_OFFENCE"
    assert app_page.locator(".record").count() == 2


def test_permanent_listings_are_marked_apart_from_fixed_ones(app_page, api):
    signed_in(app_page, api)
    search_from_nairobi(app_page)
    permanent = app_page.locator(".record.permanent")
    assert permanent.count() == 2
    assert "Permanently, repeat conviction" in permanent.first.inner_text()
    assert "Until Jan 2031" in app_page.locator(".record:not(.permanent)").first.inner_text()


def test_empty_result_says_so_without_claiming_safety(app_page, api):
    api.records = []
    signed_in(app_page, api)
    search_from_nairobi(app_page)
    text = app_page.locator("#list").inner_text()
    assert "No listed convictions within 15 km" in text and "does not mean an area is risk-free" in text


def test_nothing_is_shown_as_a_result_before_the_first_search(app_page, api):
    signed_in(app_page, api)
    assert "Choose Search near me" in app_page.locator("#list").inner_text()
    assert app_page.locator(".record").count() == 0


def test_record_fields_are_escaped_so_markup_in_data_cannot_run(app_page, api):
    api.records = [record(
        'X"><b id=pwn>', "SEXUAL_ASSAULT", "<script>window.__xss = 1</script>", 3,
        area='<img src=x onerror="window.__xss = 1">',
    )]
    signed_in(app_page, api)
    search_from_nairobi(app_page)
    assert app_page.evaluate("window.__xss") is None
    assert app_page.locator(".record img, .record script, #pwn").count() == 0
    assert "<script>window.__xss = 1</script>" in app_page.locator(".record .what").inner_text()
    assert app_page.locator(".record form").get_attribute("data-record") == 'X"><b id=pwn>'


def test_expired_session_sends_the_user_back_to_sign_in(app_page, api):
    api.statuses["nearby"] = 401
    api.details["nearby"] = "Your session has expired. Sign in again"
    signed_in(app_page, api)
    start_search(app_page)
    app_page.wait_for_selector("#login:not([hidden])")
    assert app_page.evaluate("sessionStorage.getItem('ngao_token')") is None


def test_daily_limit_message_reaches_the_user(app_page, api):
    api.statuses["nearby"] = 429
    api.details["nearby"] = "Daily search limit reached. Try again tomorrow"
    signed_in(app_page, api)
    start_search(app_page)
    app_page.wait_for_selector("#search-error:not([hidden])")
    assert app_page.locator("#search-error").inner_text() == "Daily search limit reached. Try again tomorrow"


def test_signing_out_clears_the_session_and_the_report_list(app_page, api):
    api.my_reports = [{"reference": 9, "public_record_id": "D-1", "status": "RESOLVED", "review_by": None, "resolution_note": "Done"}]
    signed_in(app_page, api)
    app_page.wait_for_selector("#reports:not([hidden])")
    app_page.click("#signout")
    app_page.wait_for_selector("#welcome:not([hidden])")
    assert app_page.evaluate("sessionStorage.getItem('ngao_token')") is None
    assert app_page.locator("#reports").is_hidden()


def test_wrong_password_shows_the_server_message(app_page, api):
    open_site(app_page, api)
    app_page.click("#nav-login")
    app_page.fill("#login-form [name=email]", "wrong@example.co.ke")
    app_page.fill("#login-form [name=password]", "not-the-password")
    app_page.click("#login-form button[type=submit]")
    app_page.wait_for_selector("#login-error:not([hidden])")
    assert app_page.locator("#login-error").inner_text() == "Wrong email or password"


def test_signing_in_to_an_unconfirmed_account_sends_new_codes_automatically(app_page, api):
    open_site(app_page, api)
    app_page.click("#nav-login")
    app_page.fill("#login-form [name=email]", "unconfirmed@example.co.ke")
    app_page.fill("#login-form [name=password]", "a-long-password")
    app_page.click("#login-form button[type=submit]")
    app_page.wait_for_selector("#verify:not([hidden])")
    assert "we sent new codes" in app_page.locator("#demo-codes").inner_text()
    assert api.resends == [{"email": "unconfirmed@example.co.ke", "password": "a-long-password"}]


def test_send_new_codes_button_asks_again_and_says_the_old_ones_are_void(app_page, api):
    open_site(app_page, api)
    fill_signup(app_page)
    app_page.click("#signup-form button[type=submit]")
    app_page.wait_for_selector("#verify:not([hidden])")
    app_page.click("#resend")
    app_page.wait_for_function("document.getElementById('demo-codes').textContent.includes('old ones no longer work')")
    assert api.resends[-1]["password"] == "a-long-password"
    assert "111222" in app_page.locator("#demo-codes").inner_text()


@pytest.mark.parametrize("delivered,named", [
    ({"email": True, "phone": False}, "phone code"),
    ({"email": False, "phone": True}, "email code"),
    ({"email": False, "phone": False}, "email or phone code"),
])
def test_when_a_code_is_not_delivered_the_user_is_told_which_one_and_is_not_stranded(app_page, api, delivered, named):
    api.delivered = delivered
    open_site(app_page, api)
    fill_signup(app_page)
    app_page.click("#signup-form button[type=submit]")
    app_page.wait_for_selector("#verify:not([hidden])")
    notice = app_page.locator("#demo-codes").inner_text()
    assert f"Your account is saved, but we could not send your {named}" in notice
    assert app_page.locator("#verify-email").inner_text() == "wanjiku@example.co.ke"
    assert app_page.locator("#resend").is_enabled()


def test_when_both_codes_are_delivered_no_problem_is_reported(app_page, api):
    open_site(app_page, api)
    fill_signup(app_page)
    app_page.click("#signup-form button[type=submit]")
    app_page.wait_for_selector("#verify:not([hidden])")
    assert "could not send" not in app_page.locator("#demo-codes").inner_text()


def test_wrong_confirmation_code_shows_the_error_and_keeps_the_form(app_page, api):
    api.statuses["verify"] = 400
    api.details["verify"] = "One or both codes are wrong"
    open_site(app_page, api)
    fill_signup(app_page)
    app_page.click("#signup-form button[type=submit]")
    app_page.wait_for_selector("#verify:not([hidden])")
    app_page.fill("#verify-form [name=email_code]", "000000")
    app_page.fill("#verify-form [name=phone_code]", "000000")
    app_page.click("#verify-form button[type=submit]")
    app_page.wait_for_selector("#verify-error:not([hidden])")
    assert app_page.locator("#verify-error").inner_text() == "One or both codes are wrong"
    assert app_page.locator("#verify").is_visible()


def test_validation_errors_from_the_server_are_readable(app_page, api):
    api.statuses["register"] = 422
    open_site(app_page, api)
    fill_signup(app_page)
    api.details["register"] = [{"msg": "Value error, Enter a Kenyan mobile number"}, {"msg": "Value error, Enter your 7 or 8 digit national ID number"}]
    app_page.click("#signup-form button[type=submit]")
    app_page.wait_for_selector("#signup-error:not([hidden])")
    assert app_page.locator("#signup-error").inner_text() == "Enter a Kenyan mobile number. Enter your 7 or 8 digit national ID number"


def test_report_form_submits_and_shows_the_reference_and_deadline(app_page, api):
    signed_in(app_page, api)
    search_from_nairobi(app_page)
    first = app_page.locator(".record").first
    first.locator("summary").click()
    first.locator("textarea").fill("The court file shows a different person with the same name.")
    first.locator("button[type=submit]").click()
    first.locator(".notice").wait_for(state="visible")
    assert "reference is 17" in first.locator(".notice").inner_text()
    assert "29 Oct 2026" in first.locator(".notice").inner_text()
    sent = api.requests_to("/corrections")[0]
    assert sent["path"] == "/api/v1/safety/records/D-1/corrections"
    assert sent["body"]["reason"] == "WRONG_PERSON"


def test_report_form_shows_the_server_refusal_and_lets_the_user_retry(app_page, api):
    api.statuses["report"] = 409
    api.details["report"] = "You already have an open report for this record"
    signed_in(app_page, api)
    search_from_nairobi(app_page)
    first = app_page.locator(".record").first
    first.locator("summary").click()
    first.locator("textarea").fill("The court file shows a different person with the same name.")
    first.locator("button[type=submit]").click()
    first.locator(".error").wait_for(state="visible")
    assert first.locator(".error").inner_text() == "You already have an open report for this record"
    assert first.locator("button[type=submit]").is_enabled()


def test_your_reports_lists_status_deadline_and_reviewer_note(app_page, api):
    api.my_reports = [
        {"reference": 17, "public_record_id": "D-1", "status": "IN_REVIEW", "review_by": "2026-10-29T09:00:00Z", "resolution_note": None},
        {"reference": 9, "public_record_id": "D-2", "status": "RESOLVED", "review_by": None, "resolution_note": "Confirmed with the registry."},
    ]
    signed_in(app_page, api)
    app_page.click("#reports summary")
    text = app_page.locator("#reports-list").inner_text()
    assert "Being reviewed" in text and "29 Oct 2026" in text
    assert "Accepted" in text and "Confirmed with the registry." in text


def test_search_service_failure_is_shown_not_swallowed(app_page, api):
    api.statuses["nearby"] = 503
    api.details["nearby"] = "Service unavailable"
    signed_in(app_page, api)
    start_search(app_page)
    app_page.wait_for_selector("#search-error:not([hidden])")
    assert app_page.locator("#search-error").inner_text() == "Service unavailable"


def test_missing_coordinates_are_stopped_before_any_request(app_page, api):
    signed_in(app_page, api)
    app_page.evaluate("document.querySelector('.controls details').open = true")
    app_page.fill("#lat", "")
    app_page.fill("#lon", "36.8")
    app_page.click("#search-coords")
    assert "valid latitude and longitude" in app_page.locator("#search-error").inner_text()
    assert api.requests_to("/nearby") == []


def test_when_the_server_cannot_load_settings_the_page_says_so(app_page, api):
    api.statuses["categories"] = 503
    open_site(app_page, api)
    assert "could not load its settings" in app_page.locator("#boot-error").inner_text()
    assert app_page.locator("#welcome").is_visible()


def test_a_smaller_server_radius_is_used_and_hides_the_bands_beyond_it(app_page, api):
    api.max_radius = 10
    signed_in(app_page, api)
    search_from_nairobi(app_page)
    assert api.requests_to("/nearby")[0]["body"]["radius_km"] == 10
    hidden = app_page.evaluate("[...document.querySelectorAll('#bands button')].map(b => b.dataset.band + ':' + b.hidden)")
    assert hidden == ["5:false", "10:false", "15:true"]
    assert "within 10 km" in app_page.locator("#results-sub").inner_text()
    assert app_page.locator(".record").count() == 3


def test_moving_between_screens_moves_keyboard_focus_to_the_new_heading(app_page, api):
    open_site(app_page, api)
    app_page.click("[data-go=signup]")
    assert app_page.evaluate("document.activeElement.tagName") == "H2"
    assert app_page.evaluate("document.activeElement.textContent") == "Create your account"


def test_every_control_has_a_name_and_every_field_a_label(app_page, api):
    signed_in(app_page, api)
    search_from_nairobi(app_page)
    unnamed = app_page.evaluate("""[...document.querySelectorAll('button')]
        .filter(b => b.offsetParent !== null && !b.textContent.trim() && !b.getAttribute('aria-label')).length""")
    unlabelled = app_page.evaluate("[...document.querySelectorAll('input, select, textarea')].filter(el => !el.closest('label')).length")
    assert unnamed == 0 and unlabelled == 0
    assert app_page.locator("html").get_attribute("lang") == "en"
    assert app_page.locator("main").count() == 1


@pytest.mark.parametrize("screen", ["welcome", "signup", "search"])
def test_no_sideways_scrolling_on_a_phone(new_page, api, screen):
    page = new_page(390, 844)
    if screen == "search":
        signed_in(page, api)
        search_from_nairobi(page)
    else:
        open_site(page, api)
        if screen == "signup":
            page.click("[data-go=signup]")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_an_expired_session_goes_straight_to_sign_in_without_showing_search(app_page, api):
    api.statuses["session"] = 401
    with_stored_token(app_page, api, "old-token")
    app_page.wait_for_selector("#login:not([hidden])")
    assert app_page.locator("#search").is_hidden()
    assert app_page.evaluate("sessionStorage.getItem('ngao_token')") is None
    assert api.requests_to("/safety/corrections", "GET") == []


def test_a_valid_session_is_checked_once_then_search_opens(app_page, api):
    signed_in(app_page, api)
    assert len(api.requests_to("/auth/session", "GET")) == 1
    assert app_page.locator("#login").is_hidden()


def test_a_server_hiccup_during_the_session_check_does_not_sign_the_user_out(app_page, api):
    api.statuses["session"] = 503
    signed_in(app_page, api)
    assert app_page.evaluate("sessionStorage.getItem('ngao_token')") == "test-token"


@pytest.mark.parametrize("demo,hidden", [(True, False), (False, True)])
def test_demo_mode_is_labelled_on_the_sign_up_screen_only_when_it_applies(app_page, api, demo, hidden):
    api.demo_mode = demo
    open_site(app_page, api)
    assert app_page.evaluate("document.getElementById('demo-id-note').hidden") is hidden
    if demo:
        app_page.click("[data-go=signup]")
        assert "every record is fictional" in app_page.locator("#demo-id-note").inner_text()


def test_a_reporter_is_told_when_their_report_is_the_reason_a_record_is_hidden(app_page, api):
    api.my_reports = [
        {"reference": 17, "public_record_id": "D-1", "status": "IN_REVIEW", "review_by": "2026-10-29T09:00:00Z", "record_hidden": True, "resolution_note": None},
        {"reference": 18, "public_record_id": "D-2", "status": "OPEN", "review_by": "2026-11-10T09:00:00Z", "record_hidden": False, "resolution_note": None},
    ]
    signed_in(app_page, api)
    app_page.click("#reports summary")
    reports = app_page.locator("#reports-list .my-report")
    assert "hidden from other people while we check it" in reports.nth(0).inner_text()
    assert "hidden" not in reports.nth(1).inner_text()


def test_a_search_from_outside_the_service_area_explains_why(app_page, api):
    api.statuses["nearby"] = 422
    api.details["nearby"] = [{"msg": "Value error, Searches are only available in and near Kenya"}]
    signed_in(app_page, api)
    start_search(app_page)
    app_page.wait_for_selector("#search-error:not([hidden])")
    assert app_page.locator("#search-error").inner_text() == "Searches are only available in and near Kenya"
