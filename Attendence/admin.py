# Attendence/admin.py
import streamlit as st
import pandas as pd
from github import GithubException
from .clients import create_supabase_client, create_github_repo
from .config import get_env
from .utils import current_ist_date
from .logger import get_logger

logger = get_logger(__name__)


# ---------- Setup clients ----------
def setup_clients():
    """
    Returns: (supabase, repo, admin_username, admin_password)
    Repo may be None if GitHub not configured.
    """
    supabase = create_supabase_client()
    gh, repo = create_github_repo()

    admin_user = get_env("ADMIN_USERNAME")
    admin_pass = get_env("ADMIN_PASSWORD")

    if not admin_user or not admin_pass:
        raise RuntimeError("Admin credentials missing")

    return supabase, repo, admin_user, admin_pass


# ---------- Admin Login ----------
def admin_login(admin_user, admin_pass):

    if "admin_logged_in" not in st.session_state:
        st.session_state.admin_logged_in = False

    if not st.session_state.admin_logged_in:

        with st.form("admin_login"):

            username = st.text_input("Username")
            password = st.text_input("Password", type="password")

            submitted = st.form_submit_button("🔐 Login")

            if submitted:

                if username == admin_user and password == admin_pass:
                    st.session_state.admin_logged_in = True
                    st.rerun()
                else:
                    st.error("Invalid credentials")

        st.stop()


# ---------- Sidebar controls ----------
def sidebar_controls(supabase):

    try:

        with st.sidebar:

            st.markdown("## ➕ Create Class")

            class_input = st.text_input("New Class Name")

            if st.button("➕ Add Class"):

                if class_input.strip():

                    exists = (
                        supabase.table("classroom_settings")
                        .select("*")
                        .eq("class_name", class_input)
                        .execute()
                        .data
                    )

                    if exists:
                        st.warning("Class already exists.")

                    else:

                        supabase.table("classroom_settings").insert(
                            {
                                "class_name": class_input,
                                "code": "1234",
                                "daily_limit": 10,
                                "is_open": False,
                            }
                        ).execute()

                        st.success(f"Class '{class_input}' created.")
                        st.rerun()

            if st.button("🚪 Logout"):
                st.session_state.admin_logged_in = False
                st.rerun()

            st.markdown("## 🗑️ Delete Class")

            delete_target = st.text_input("Enter class to delete")

            if st.button("Delete This Class"):

                if delete_target.strip():

                    st.warning(
                        "This will permanently delete the class and all data."
                    )

                    if st.text_input("Type DELETE to confirm") == "DELETE":

                        supabase.table("attendance").delete().eq(
                            "class_name", delete_target
                        ).execute()

                        supabase.table("roll_map").delete().eq(
                            "class_name", delete_target
                        ).execute()

                        supabase.table("classroom_settings").delete().eq(
                            "class_name", delete_target
                        ).execute()

                        st.success("Class deleted.")
                        st.rerun()

    except Exception as e:

        logger.exception("Error in sidebar_controls")
        st.error(f"Sidebar error: {e}")


# ---------- Class Controls ----------
def class_controls(supabase):

    try:

        classes_resp = (
            supabase.table("classroom_settings").select("*").execute()
        )

        classes = classes_resp.data or []

    except Exception:

        logger.exception("Failed to fetch classes")
        st.error("Failed to fetch classes from Supabase.")
        st.stop()
        return None

    if not classes:

        st.warning("No classes found.")
        st.stop()

    selected_class = st.selectbox(
        "📚 Select a Class", [c["class_name"] for c in classes]
    )

    config = next(
        (c for c in classes if c["class_name"] == selected_class), None
    )

    if not config:

        st.error("Selected class config missing.")
        st.stop()

    st.markdown(f"**Current Code:** `{config['code']}`")
    st.markdown(f"**Current Limit:** `{config['daily_limit']}`")

    is_open = config.get("is_open", False)

    other_open = [
        c["class_name"]
        for c in classes
        if c.get("is_open") and c["class_name"] != selected_class
    ]

    st.subheader("🛠️ Attendance Controls")

    st.info(f"Status: {'OPEN' if is_open else 'CLOSED'}")

    col1, col2 = st.columns(2)

    with col1:

        if st.button("✅ Open Attendance"):

            if other_open:

                st.warning(
                    f"Close other open classes: {', '.join(other_open)}"
                )

            else:

                try:

                    supabase.table("classroom_settings").update(
                        {"is_open": True}
                    ).eq("class_name", selected_class).execute()

                    st.rerun()

                except Exception:

                    logger.exception("Failed to open attendance")
                    st.error("Failed to open attendance.")

    with col2:

        if st.button("❌ Close Attendance"):

            try:

                supabase.table("classroom_settings").update(
                    {"is_open": False}
                ).eq("class_name", selected_class).execute()

                st.rerun()

            except Exception:

                logger.exception("Failed to close attendance")
                st.error("Failed to close attendance.")

    with st.expander("🔄 Update Code & Limit"):

        new_code = st.text_input("New Code", value=config["code"])

        new_limit = st.number_input(
            "New Limit",
            min_value=1,
            value=config["daily_limit"],
            step=1,
        )

        if st.button("📏 Save Settings"):

            try:

                supabase.table("classroom_settings").update(
                    {
                        "code": new_code,
                        "daily_limit": new_limit,
                    }
                ).eq("class_name", selected_class).execute()

                st.success("✅ Settings updated.")
                st.rerun()

            except Exception:

                logger.exception("Failed to update settings")
                st.error("Failed to update settings.")

    return selected_class


# ---------- Attendance Matrix ----------
def show_matrix_and_push(supabase, repo, selected_class):

    try:

        records_resp = (
            supabase.table("attendance")
            .select("*")
            .eq("class_name", selected_class)
            .order("date", desc=True)
            .execute()
        )

        records = records_resp.data or []

    except Exception:

        logger.exception("Failed to fetch attendance records")
        st.error("Failed to fetch attendance records.")
        return

    if not records:

        st.info("No attendance data yet.")
        return

    df = pd.DataFrame(records)

    df["status"] = "P"

    pivot_df = (
        df.pivot_table(
            index=["roll_number", "name"],
            columns="date",
            values="status",
            aggfunc="first",
            fill_value="A",
        )
        .reset_index()
    )

    pivot_df["roll_number"] = pd.to_numeric(
        pivot_df["roll_number"], errors="coerce"
    )

    pivot_df = pivot_df.dropna(subset=["roll_number"])

    pivot_df["roll_number"] = pivot_df["roll_number"].astype(int)

    pivot_df = pivot_df.sort_values("roll_number")

    st.dataframe(pivot_df, width="stretch")

    st.download_button(
        "⬇️ Download CSV",
        pivot_df.to_csv(index=False).encode(),
        f"{selected_class}_matrix.csv",
        "text/csv",
    )

    if st.button("🚀 Push to GitHub"):

        if repo is None:

            st.error("GitHub not configured.")
            return

        filename = f"records/attendance_matrix_{selected_class}_{current_ist_date().replace('-', '')}.csv"

        file_content = pivot_df.to_csv(index=False)

        try:

            existing = repo.get_contents(filename, ref="main")

            repo.update_file(
                filename,
                "Update attendance matrix",
                file_content,
                existing.sha,
                branch="main",
            )

            st.success("Updated existing file")

        except GithubException as e:

            if e.status == 404:

                repo.create_file(
                    filename,
                    "Create attendance matrix",
                    file_content,
                    branch="main",
                )

                st.success("Created new file")

            else:

                st.error("GitHub error")


# ---------- Main Panel ----------
def show_admin_panel():

    st.set_page_config(
        page_title="Admin Panel",
        layout="wide",
        page_icon="👩‍🏫",
    )

    st.markdown(
        """
        <h1 style='text-align:center;color:#4B8BBE;'>👩‍🏫 Admin Control Panel</h1>
        <hr>
        """,
        unsafe_allow_html=True,
    )

    try:

        supabase, repo, admin_user, admin_pass = setup_clients()

    except Exception:

        st.error(
            "Failed to initialize clients. Check logs / environment."
        )
        return

    admin_login(admin_user, admin_pass)

    sidebar_controls(supabase)

    selected_class = class_controls(supabase)

    if selected_class:

        show_matrix_and_push(supabase, repo, selected_class)