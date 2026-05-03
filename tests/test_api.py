import base64


TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/w8AAgMBApW3G1cAAAAASUVORK5CYII="
)


def register_user(client, username: str, email: str, password: str = "password123", full_name: str | None = None):
    payload = {
        "username": username,
        "email": email,
        "password": password,
        "full_name": full_name or username.title(),
    }
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 200, response.text
    return payload


def login_user(client, login: str, password: str = "password123") -> dict:
    response = client.post("/api/auth/login", json={"login": login, "password": password})
    assert response.status_code == 200, response.text
    data = response.json()
    token = data["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_project(
    client,
    headers: dict[str, str],
    *,
    title: str = "Study Buddy",
    status: str = "active",
    applications_open: bool = True,
) -> dict:
    payload = {
        "title": title,
        "description": "A collaborative student project for matching teammates.",
        "tags": ["fastapi", "student"],
        "required_roles": ["backend", "frontend"],
        "github_url": "https://github.com/example/study-buddy",
        "demo_url": "https://example.com/demo",
        "contact_info": "@studybuddy",
        "status": status,
        "applications_open": applications_open,
    }
    response = client.post("/api/projects", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["project"]


def test_auth_oauth_token_and_me(client):
    register_user(client, "owner", "owner@example.com", full_name="Owner User")

    login_response = client.post("/api/auth/login", json={"login": "owner", "password": "password123"})
    assert login_response.status_code == 200, login_response.text
    login_data = login_response.json()
    assert login_data["token_type"] == "bearer"
    assert login_data["access_token"]

    token_response = client.post(
        "/api/auth/token",
        data={"username": "owner", "password": "password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert token_response.status_code == 200, token_response.text
    token_data = token_response.json()
    assert token_data["token_type"] == "bearer"
    assert token_data["access_token"]

    me_response = client.get("/api/me", headers={"Authorization": f"Bearer {token_data['access_token']}"})
    assert me_response.status_code == 200, me_response.text
    me = me_response.json()
    assert me["username"] == "owner"
    assert me["email"] == "owner@example.com"


def test_profile_update_and_photo_upload(client):
    register_user(client, "designer", "designer@example.com", full_name="Design Lead")
    headers = login_user(client, "designer")

    update_response = client.put(
        "/api/profile/me",
        json={
            "full_name": "Design Lead",
            "bio": "Product designer focused on student tools.",
            "skills": ["figma", "ux"],
            "roles": ["design"],
            "links": ["https://t.me/designer"],
        },
        headers=headers,
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["user"]["roles"] == ["design"]

    photo_response = client.post(
        "/api/profile/me/photo",
        json={
            "file_name": "avatar.png",
            "mime_type": "image/png",
            "content_base64": TINY_PNG_BASE64,
        },
        headers=headers,
    )
    assert photo_response.status_code == 200, photo_response.text
    assert photo_response.json()["photo_url"].startswith("/media/profile_photos/")

    profile_response = client.get("/api/profile/me", headers=headers)
    assert profile_response.status_code == 200, profile_response.text
    profile = profile_response.json()
    assert profile["user"]["bio"] == "Product designer focused on student tools."
    assert profile["user"]["photo_url"].startswith("/media/profile_photos/")

    delete_photo_response = client.delete("/api/profile/me/photo", headers=headers)
    assert delete_photo_response.status_code == 200, delete_photo_response.text
    assert delete_photo_response.json()["user"]["photo_url"] is None


def test_archived_projects_are_hidden_from_public(client):
    register_user(client, "owner", "owner@example.com")
    owner_headers = login_user(client, "owner")

    active_project = create_project(client, owner_headers, title="Active Project", status="active")
    archived_project = create_project(client, owner_headers, title="Archived Project", status="archived")

    register_user(client, "viewer", "viewer@example.com")
    viewer_headers = login_user(client, "viewer")

    list_response = client.get("/api/projects", headers=viewer_headers)
    assert list_response.status_code == 200, list_response.text
    titles = [item["title"] for item in list_response.json()["items"]]
    assert "Active Project" in titles
    assert "Archived Project" not in titles

    public_profile_response = client.get("/api/profile/owner", headers=viewer_headers)
    assert public_profile_response.status_code == 200, public_profile_response.text
    public_titles = [item["title"] for item in public_profile_response.json()["projects"]]
    assert "Active Project" in public_titles
    assert "Archived Project" not in public_titles

    hidden_project_response = client.get(f"/api/projects/{archived_project['id']}", headers=viewer_headers)
    assert hidden_project_response.status_code == 404, hidden_project_response.text

    owner_archived_response = client.get(f"/api/projects/{archived_project['id']}", headers=owner_headers)
    assert owner_archived_response.status_code == 200, owner_archived_response.text
    assert owner_archived_response.json()["project"]["title"] == "Archived Project"

    active_project_response = client.get(f"/api/projects/{active_project['id']}", headers=viewer_headers)
    assert active_project_response.status_code == 200, active_project_response.text


def test_application_notifications_and_single_status_change(client):
    register_user(client, "owner", "owner@example.com", full_name="Owner")
    owner_headers = login_user(client, "owner")
    project = create_project(client, owner_headers, title="Team Finder", status="active")

    register_user(client, "applicant", "applicant@example.com", full_name="Happy Student")
    applicant_headers = login_user(client, "applicant")

    apply_response = client.post(
        f"/api/projects/{project['id']}/applications",
        json={"message": "I have backend experience and want to join this project."},
        headers=applicant_headers,
    )
    assert apply_response.status_code == 200, apply_response.text
    application = apply_response.json()["application"]
    assert application["status"] == "new"

    owner_notifications = client.get("/api/notifications", headers=owner_headers)
    assert owner_notifications.status_code == 200, owner_notifications.text
    owner_items = owner_notifications.json()["items"]
    assert any(item["type"] == "new_application" for item in owner_items)
    assert owner_items[0]["title"] == "Новый отклик на проект"
    assert "откликнулся на ваш проект" in owner_items[0]["message"]

    owner_applications = client.get(f"/api/projects/{project['id']}/applications", headers=owner_headers)
    assert owner_applications.status_code == 200, owner_applications.text
    assert owner_applications.json()["items"][0]["applicant_username"] == "applicant"

    accept_response = client.patch(
        f"/api/applications/{application['id']}",
        json={"status": "accepted", "assigned_role": "backend"},
        headers=owner_headers,
    )
    assert accept_response.status_code == 200, accept_response.text
    assert accept_response.json()["application"]["status"] == "accepted"
    assert accept_response.json()["application"]["assigned_role"] == "backend"

    second_change_response = client.patch(
        f"/api/applications/{application['id']}",
        json={"status": "rejected"},
        headers=owner_headers,
    )
    assert second_change_response.status_code == 400, second_change_response.text

    applicant_notifications = client.get("/api/notifications", headers=applicant_headers)
    assert applicant_notifications.status_code == 200, applicant_notifications.text
    applicant_items = applicant_notifications.json()["items"]
    assert any(item["type"] == "application_status" for item in applicant_items)
    assert applicant_items[0]["title"] == "Статус отклика обновлён"
    assert "принят на роль" in applicant_items[0]["message"]

    duplicate_apply_response = client.post(
        f"/api/projects/{project['id']}/applications",
        json={"message": "Trying to apply again should fail."},
        headers=applicant_headers,
    )
    assert duplicate_apply_response.status_code == 400, duplicate_apply_response.text


def test_registration_duplicates_and_unauthorized_access(client):
    register_user(client, "owner", "owner@example.com")

    duplicate_username = client.post(
        "/api/auth/register",
        json={
            "username": "owner",
            "email": "other@example.com",
            "password": "password123",
            "full_name": "Other User",
        },
    )
    assert duplicate_username.status_code == 400, duplicate_username.text

    duplicate_email = client.post(
        "/api/auth/register",
        json={
            "username": "other",
            "email": "owner@example.com",
            "password": "password123",
            "full_name": "Other User",
        },
    )
    assert duplicate_email.status_code == 400, duplicate_email.text

    me_response = client.get("/api/me")
    assert me_response.status_code == 401, me_response.text

    notifications_response = client.get("/api/notifications")
    assert notifications_response.status_code == 401, notifications_response.text


def test_project_sorting_pagination_and_owner_filter(client):
    register_user(client, "owner", "owner@example.com")
    owner_headers = login_user(client, "owner")

    create_project(client, owner_headers, title="Project A")
    create_project(client, owner_headers, title="Project B")
    create_project(client, owner_headers, title="Project C")

    newest_response = client.get(
        "/api/projects?page=1&page_size=2&sort_order=newest&owner=owner",
        headers=owner_headers,
    )
    assert newest_response.status_code == 200, newest_response.text
    newest_data = newest_response.json()
    assert newest_data["total"] == 3
    assert newest_data["pages"] == 2
    newest_titles = [item["title"] for item in newest_data["items"]]
    assert newest_titles == ["Project C", "Project B"]

    oldest_response = client.get(
        "/api/projects?page=1&page_size=2&sort_order=oldest&owner=owner",
        headers=owner_headers,
    )
    assert oldest_response.status_code == 200, oldest_response.text
    oldest_titles = [item["title"] for item in oldest_response.json()["items"]]
    assert oldest_titles == ["Project A", "Project B"]

    second_page_response = client.get(
        "/api/projects?page=2&page_size=2&sort_order=oldest&owner=owner",
        headers=owner_headers,
    )
    assert second_page_response.status_code == 200, second_page_response.text
    second_page_titles = [item["title"] for item in second_page_response.json()["items"]]
    assert second_page_titles == ["Project C"]


def test_notifications_can_be_marked_as_read(client):
    register_user(client, "owner", "owner@example.com")
    owner_headers = login_user(client, "owner")
    project = create_project(client, owner_headers, title="Notifier Project")

    register_user(client, "applicant", "applicant@example.com")
    applicant_headers = login_user(client, "applicant")
    apply_response = client.post(
        f"/api/projects/{project['id']}/applications",
        json={"message": "I can contribute to backend and testing."},
        headers=applicant_headers,
    )
    assert apply_response.status_code == 200, apply_response.text

    notifications_response = client.get("/api/notifications", headers=owner_headers)
    assert notifications_response.status_code == 200, notifications_response.text
    notifications_data = notifications_response.json()
    assert notifications_data["unread_count"] >= 1
    notification_id = notifications_data["items"][0]["id"]

    mark_read_response = client.post(f"/api/notifications/{notification_id}/read", headers=owner_headers)
    assert mark_read_response.status_code == 200, mark_read_response.text
    assert mark_read_response.json()["message"] == "Уведомление отмечено как прочитанное."
    assert mark_read_response.json()["notification"]["is_read"] is True

    refreshed_notifications = client.get("/api/notifications", headers=owner_headers)
    assert refreshed_notifications.status_code == 200, refreshed_notifications.text
    assert refreshed_notifications.json()["unread_count"] == 0


def test_dashboard_overview_returns_metrics_and_recent_items(client):
    register_user(client, "owner", "owner@example.com", full_name="Owner User")
    owner_headers = login_user(client, "owner")

    create_project(client, owner_headers, title="Alpha")
    create_project(client, owner_headers, title="Beta", status="archived")

    register_user(client, "applicant", "applicant@example.com", full_name="Applicant User")
    applicant_headers = login_user(client, "applicant")
    register_user(client, "second", "second@example.com", full_name="Second Member")
    second_headers = login_user(client, "second")

    apply_response = client.post(
        "/api/projects/1/applications",
        json={"message": "I can help with backend and analytics for this project."},
        headers=applicant_headers,
    )
    assert apply_response.status_code == 200, apply_response.text
    application_id = apply_response.json()["application"]["id"]

    status_response = client.patch(
        f"/api/applications/{application_id}",
        json={"status": "accepted", "assigned_role": "analyst"},
        headers=owner_headers,
    )
    assert status_response.status_code == 200, status_response.text

    second_apply_response = client.post(
        "/api/projects/1/applications",
        json={"message": "I can help with frontend and UI in this project."},
        headers=second_headers,
    )
    assert second_apply_response.status_code == 200, second_apply_response.text
    second_application_id = second_apply_response.json()["application"]["id"]

    second_status_response = client.patch(
        f"/api/applications/{second_application_id}",
        json={"status": "accepted", "assigned_role": "frontend"},
        headers=owner_headers,
    )
    assert second_status_response.status_code == 200, second_status_response.text

    overview_response = client.get("/api/dashboard/overview", headers=owner_headers)
    assert overview_response.status_code == 200, overview_response.text
    overview = overview_response.json()

    assert overview["user"]["username"] == "owner"
    assert overview["metrics"]["my_projects_total"] == 2
    assert overview["metrics"]["my_projects_active"] == 1
    assert overview["metrics"]["my_projects_archived"] == 1
    assert overview["metrics"]["incoming_applications_total"] == 2
    assert overview["metrics"]["incoming_applications_new"] == 0
    assert overview["metrics"]["notifications_unread"] >= 1
    assert overview["recent_projects"][0]["title"] == "Beta"
    incoming_usernames = {item["applicant_username"] for item in overview["incoming_applications"]}
    assert {"applicant", "second"} <= incoming_usernames
    team_member_roles = {member["username"]: member["role"] for member in overview["team_members"]}
    assert team_member_roles["applicant"] == "analyst"
    assert team_member_roles["second"] == "frontend"
    assert overview["team_projects"][0]["project_title"] == "Alpha"
    assert overview["team_projects"][0]["owner_username"] == "owner"
    project_member_usernames = {member["username"] for member in overview["team_projects"][0]["members"]}
    assert {"applicant", "second"} <= project_member_usernames
    assert overview["notifications"][0]["type"] == "new_application"

    applicant_overview_response = client.get("/api/dashboard/overview", headers=applicant_headers)
    assert applicant_overview_response.status_code == 200, applicant_overview_response.text
    applicant_overview = applicant_overview_response.json()
    assert applicant_overview["team_projects"][0]["project_title"] == "Alpha"
    assert applicant_overview["team_projects"][0]["owner_username"] == "owner"
    member_usernames = {member["username"] for member in applicant_overview["team_projects"][0]["members"]}
    assert {"applicant", "second"} <= member_usernames
    assert any(member["is_current_user"] is True for member in applicant_overview["team_projects"][0]["members"])


def test_non_owner_cannot_manage_other_users_project_or_applications(client):
    register_user(client, "owner", "owner@example.com")
    owner_headers = login_user(client, "owner")
    project = create_project(client, owner_headers, title="Protected Project")

    register_user(client, "viewer", "viewer@example.com")
    viewer_headers = login_user(client, "viewer")

    update_response = client.put(
        f"/api/projects/{project['id']}",
        json={
            "title": "Hacked Title",
            "description": "Should not be allowed.",
            "tags": ["hack"],
            "required_roles": ["backend"],
            "github_url": "",
            "demo_url": "",
            "contact_info": "",
            "status": "active",
            "applications_open": True,
        },
        headers=viewer_headers,
    )
    assert update_response.status_code == 403, update_response.text

    delete_response = client.delete(f"/api/projects/{project['id']}", headers=viewer_headers)
    assert delete_response.status_code == 403, delete_response.text

    list_applications_response = client.get(f"/api/projects/{project['id']}/applications", headers=viewer_headers)
    assert list_applications_response.status_code == 403, list_applications_response.text


def test_application_rules_for_own_project_archived_project_and_short_message(client):
    register_user(client, "owner", "owner@example.com")
    owner_headers = login_user(client, "owner")
    active_project = create_project(client, owner_headers, title="Own Project", status="active")
    archived_project = create_project(client, owner_headers, title="Archived Apply Project", status="archived")

    own_apply_response = client.post(
        f"/api/projects/{active_project['id']}/applications",
        json={"message": "I want to apply to my own project."},
        headers=owner_headers,
    )
    assert own_apply_response.status_code == 400, own_apply_response.text

    register_user(client, "applicant", "applicant@example.com")
    applicant_headers = login_user(client, "applicant")

    archived_apply_response = client.post(
        f"/api/projects/{archived_project['id']}/applications",
        json={"message": "I want to join an archived project."},
        headers=applicant_headers,
    )
    assert archived_apply_response.status_code == 400, archived_apply_response.text

    short_message_response = client.post(
        f"/api/projects/{active_project['id']}/applications",
        json={"message": "short"},
        headers=applicant_headers,
    )
    assert short_message_response.status_code == 422, short_message_response.text


def test_accepting_applicant_without_profile_role_requires_project_role(client):
    register_user(client, "owner", "owner@example.com")
    owner_headers = login_user(client, "owner")
    project = create_project(client, owner_headers, title="Role Required Project", status="active")

    register_user(client, "applicant", "applicant@example.com")
    applicant_headers = login_user(client, "applicant")

    apply_response = client.post(
        f"/api/projects/{project['id']}/applications",
        json={"message": "I can help and want to join this project."},
        headers=applicant_headers,
    )
    assert apply_response.status_code == 200, apply_response.text
    application_id = apply_response.json()["application"]["id"]

    missing_role_response = client.patch(
        f"/api/applications/{application_id}",
        json={"status": "accepted"},
        headers=owner_headers,
    )
    assert missing_role_response.status_code == 400, missing_role_response.text

    accepted_response = client.patch(
        f"/api/applications/{application_id}",
        json={"status": "accepted", "assigned_role": "frontend"},
        headers=owner_headers,
    )
    assert accepted_response.status_code == 200, accepted_response.text
    assert accepted_response.json()["application"]["assigned_role"] == "frontend"


def test_accepted_member_can_request_role_change_and_owner_can_approve(client):
    register_user(client, "owner", "owner@example.com")
    owner_headers = login_user(client, "owner")
    project = create_project(client, owner_headers, title="Role Change Project", status="active")

    register_user(client, "member", "member@example.com", full_name="Team Member")
    member_headers = login_user(client, "member")

    apply_response = client.post(
        f"/api/projects/{project['id']}/applications",
        json={"message": "I can contribute to design and frontend tasks in this project."},
        headers=member_headers,
    )
    assert apply_response.status_code == 200, apply_response.text
    application_id = apply_response.json()["application"]["id"]

    accept_response = client.patch(
        f"/api/applications/{application_id}",
        json={"status": "accepted", "assigned_role": "frontend"},
        headers=owner_headers,
    )
    assert accept_response.status_code == 200, accept_response.text
    assert accept_response.json()["application"]["assigned_role"] == "frontend"

    request_response = client.post(
        f"/api/applications/{application_id}/role-request",
        json={"requested_role": "designer"},
        headers=member_headers,
    )
    assert request_response.status_code == 200, request_response.text
    assert request_response.json()["application"]["requested_role"] == "designer"

    owner_view_response = client.get(f"/api/projects/{project['id']}", headers=owner_headers)
    assert owner_view_response.status_code == 200, owner_view_response.text
    assert owner_view_response.json()["applications"][0]["requested_role"] == "designer"

    approve_response = client.patch(
        f"/api/applications/{application_id}/role-request",
        json={"decision": "approved", "assigned_role": "frontend developer"},
        headers=owner_headers,
    )
    assert approve_response.status_code == 200, approve_response.text
    assert approve_response.json()["application"]["assigned_role"] == "frontend developer"
    assert approve_response.json()["application"]["requested_role"] is None

    member_project_view = client.get(f"/api/projects/{project['id']}", headers=member_headers)
    assert member_project_view.status_code == 200, member_project_view.text
    assert member_project_view.json()["current_user_application"]["assigned_role"] == "frontend developer"
    assert member_project_view.json()["current_user_application"]["requested_role"] is None

    long_request_response = client.post(
        f"/api/applications/{application_id}/role-request",
        json={"requested_role": "очень длинный запрос роли, который не должен проходить через валидацию вообще"},
        headers=member_headers,
    )
    assert long_request_response.status_code == 422, long_request_response.text


def test_owner_can_close_recruitment_and_remove_team_member(client):
    register_user(client, "owner", "owner@example.com")
    owner_headers = login_user(client, "owner")
    project = create_project(client, owner_headers, title="Closable Project", applications_open=True)

    register_user(client, "first", "first@example.com", full_name="First User")
    first_headers = login_user(client, "first")
    first_apply = client.post(
        f"/api/projects/{project['id']}/applications",
        json={"message": "I can help with backend and product tasks."},
        headers=first_headers,
    )
    assert first_apply.status_code == 200, first_apply.text
    first_application_id = first_apply.json()["application"]["id"]

    accept_response = client.patch(
        f"/api/applications/{first_application_id}",
        json={"status": "accepted", "assigned_role": "backend"},
        headers=owner_headers,
    )
    assert accept_response.status_code == 200, accept_response.text

    close_response = client.put(
        f"/api/projects/{project['id']}",
        json={
            "title": project["title"],
            "description": project["description"],
            "tags": project["tags"],
            "required_roles": project["required_roles"],
            "github_url": project["github_url"],
            "demo_url": project["demo_url"],
            "contact_info": project["contact_info"],
            "status": "active",
            "applications_open": False,
        },
        headers=owner_headers,
    )
    assert close_response.status_code == 200, close_response.text
    assert close_response.json()["project"]["applications_open"] is False

    register_user(client, "second", "second@example.com", full_name="Second User")
    second_headers = login_user(client, "second")
    closed_apply = client.post(
        f"/api/projects/{project['id']}/applications",
        json={"message": "I still want to join even when the recruitment is closed."},
        headers=second_headers,
    )
    assert closed_apply.status_code == 400, closed_apply.text

    remove_response = client.post(f"/api/applications/{first_application_id}/remove", headers=owner_headers)
    assert remove_response.status_code == 200, remove_response.text
    assert remove_response.json()["application"]["status"] == "removed"

    overview_response = client.get("/api/dashboard/overview", headers=owner_headers)
    assert overview_response.status_code == 200, overview_response.text
    overview = overview_response.json()
    assert overview["team_members"] == []


def test_public_and_private_profile_fields(client):
    register_user(client, "owner", "owner@example.com", full_name="Owner Name")
    owner_headers = login_user(client, "owner")

    client.put(
        "/api/profile/me",
        json={
            "full_name": "Owner Name",
            "bio": "Backend developer.",
            "skills": ["python"],
            "roles": ["backend"],
            "links": ["https://github.com/owner"],
        },
        headers=owner_headers,
    )

    own_profile = client.get("/api/profile/me", headers=owner_headers)
    assert own_profile.status_code == 200, own_profile.text
    assert own_profile.json()["user"]["email"] == "owner@example.com"

    register_user(client, "viewer", "viewer@example.com")
    viewer_headers = login_user(client, "viewer")
    public_profile = client.get("/api/profile/owner", headers=viewer_headers)
    assert public_profile.status_code == 200, public_profile.text
    assert "email" not in public_profile.json()["user"]
    assert public_profile.json()["user"]["roles"] == ["backend"]
