
import streamlit as st
import pandas as pd
import html

# =========================================================
# GRADEFLOW — PREMIUM STUDENT PERFORMANCE DASHBOARD
# =========================================================

st.set_page_config(
    page_title="GradeFlow | Student Intelligence",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------------------------------------------------------
# GRADING SYSTEM
# Replace these boundaries with your original Day 2
# get_grade() if that assignment used a different scale.
# ---------------------------------------------------------

def get_grade(mark):
    if mark >= 90:
        return "A"
    elif mark >= 80:
        return "B"
    elif mark >= 70:
        return "C"
    elif mark >= 60:
        return "D"
    return "F"

# ---------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------

if "students" not in st.session_state:
    st.session_state.students = []

if "notice" not in st.session_state:
    st.session_state.notice = None

# ---------------------------------------------------------
# PREMIUM STYLING
# ---------------------------------------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Outfit:wght@400;500;600;700;800;900&display=swap');

:root {
    --bg: #080D18;
    --surface: #111A2B;
    --border: #25324A;
    --text: #F3F6FF;
    --muted: #91A1BD;
    --violet: #8B7CFF;
    --cyan: #56D9EF;
}

html, body, [class*="css"], [data-testid="stApp"] {
    font-family: 'DM Sans', sans-serif;
}

.stApp {
    background:
        radial-gradient(ellipse at 8% 3%,
            rgba(97,77,220,.19), transparent 32%),
        radial-gradient(ellipse at 95% 15%,
            rgba(24,142,185,.11), transparent 30%),
        #080D18;
    color: var(--text);
}

.block-container {
    max-width: 1320px;
    padding: 2.2rem 2rem 4rem;
}

header[data-testid="stHeader"] {
    background: transparent;
}

#MainMenu, footer {
    visibility: hidden;
}

h1, h2, h3 {
    font-family: 'Outfit', sans-serif;
}

.brand {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 40px;
}

.brand-logo {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 45px;
    height: 45px;
    border-radius: 14px;
    color: white;
    font-size: 25px;
    background: linear-gradient(135deg, #7465FF, #28C7DE);
    box-shadow: 0 8px 28px #685BFF44;
}

.brand-text {
    color: #F5F7FF;
    font-family: 'Outfit', sans-serif;
    font-weight: 800;
    font-size: 25px;
    letter-spacing: -1px;
}

.brand-text span {
    color: #9B91FF;
}

.brand-tag {
    margin-left: auto;
    padding: 8px 14px;
    border: 1px solid #2B3852;
    border-radius: 30px;
    color: #AAB9D2;
    font-size: 12px;
    background: #141D2C;
}

.hero {
    padding: 15px 0 35px;
}

.eyebrow {
    color: #A399FF;
    font-weight: 800;
    font-size: 11px;
    letter-spacing: 2.7px;
    margin-bottom: 17px;
}

.hero h1 {
    font-size: clamp(39px, 5vw, 66px);
    font-weight: 800;
    line-height: 1.08;
    letter-spacing: -2.4px;
    color: #F7F8FF;
    margin: 0;
}

.gradient-text {
    background: linear-gradient(90deg,
        #A59AFF 0%, #7DB7FF 52%, #5BE1E6 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.hero p {
    color: #9BAAC3;
    font-size: 16px;
    line-height: 1.8;
    max-width: 650px;
    margin-top: 18px;
}

.section-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin: 28px 0 15px;
}

.section-title {
    color: #F3F6FF;
    font-family: 'Outfit', sans-serif;
    font-size: 21px;
    font-weight: 700;
}

.section-subtitle {
    color: #8798B4;
    font-size: 13px;
    margin-top: 4px;
}

.metric-card {
    min-height: 160px;
    background: linear-gradient(145deg,
        rgba(24,35,55,.98),
        rgba(14,23,39,.98));
    border: 1px solid #28354D;
    border-radius: 20px;
    padding: 23px;
    margin-bottom: 12px;
    position: relative;
    overflow: hidden;
    box-shadow: 0 15px 35px #00000022;
}

.metric-card:before {
    content: "";
    position: absolute;
    top: 0;
    left: 20px;
    right: 20px;
    height: 2px;
    background: linear-gradient(90deg,
        transparent, #7465FF66, transparent);
}

.metric-icon {
    color: #9C92FF;
    font-size: 19px;
    margin-bottom: 15px;
}

.metric-label {
    color: #9EACC3;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: .4px;
}

.metric-value {
    color: #F8FAFF;
    font-family: 'Outfit', sans-serif;
    font-size: 37px;
    font-weight: 800;
    margin-top: 6px;
    letter-spacing: -1px;
}

.metric-detail {
    color: #7485A0;
    font-size: 11px;
    margin-top: 5px;
}

[data-testid="stForm"] {
    background: linear-gradient(145deg, #172137, #111A2B);
    border: 1px solid #2A3850;
    border-radius: 20px;
    padding: 27px;
    box-shadow: 0 15px 35px #00000022;
}

.stTextInput label,
.stNumberInput label {
    color: #C5D1E5 !important;
    font-weight: 600 !important;
}

.stTextInput input,
.stNumberInput input {
    background: #0B1424 !important;
    border: 1px solid #34415A !important;
    border-radius: 11px !important;
    color: #F8FAFF !important;
    min-height: 47px;
}

.stTextInput input:focus,
.stNumberInput input:focus {
    border-color: #9387FF !important;
    box-shadow: 0 0 0 2px #7465FF33 !important;
}

.stFormSubmitButton button {
    background: linear-gradient(100deg,
        #796AFF, #5748DC) !important;
    color: white !important;
    border: none !important;
    border-radius: 11px !important;
    min-height: 47px;
    font-weight: 800 !important;
    box-shadow: 0 8px 22px #5C4BE044;
}

.stFormSubmitButton button:hover {
    background: linear-gradient(100deg,
        #9185FF, #6859EF) !important;
}

.stButton button {
    border-radius: 11px !important;
    min-height: 42px;
}

[data-testid="stDataFrame"] {
    border: 1px solid #29364C;
    border-radius: 15px;
    overflow: hidden;
}

.empty-state {
    background: linear-gradient(145deg,
        #172137, #111A2B);
    border: 1px dashed #34425A;
    border-radius: 20px;
    text-align: center;
    padding: 65px 20px;
}

.empty-icon {
    color: #9B91FF;
    font-size: 43px;
    margin-bottom: 15px;
}

.empty-title {
    color: #F5F7FF;
    font-size: 21px;
    font-weight: 800;
}

.empty-subtitle {
    color: #94A4BF;
    font-size: 14px;
    margin-top: 8px;
}

.grade-chip {
    display: inline-block;
    padding: 7px 14px;
    border-radius: 9px;
    font-weight: 800;
    font-size: 13px;
    margin-right: 7px;
    margin-bottom: 8px;
}

.grade-A {background:#123B33;color:#5BE6AC;}
.grade-B {background:#17344A;color:#65C9FF;}
.grade-C {background:#39301A;color:#F3CA65;}
.grade-D {background:#443021;color:#FFB16C;}
.grade-F {background:#441F2B;color:#FF8197;}

.footer {
    margin-top: 55px;
    border-top: 1px solid #263249;
    padding-top: 20px;
    color: #7889A4;
    font-size: 12px;
    display: flex;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
}

@media (max-width: 650px) {
    .block-container {
        padding: 1.2rem .9rem 3rem;
    }
    .hero h1 {
        letter-spacing: -1px;
    }
    .brand-tag {
        display: none;
    }
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# SMALL UI HELPERS
# ---------------------------------------------------------

def section(title, subtitle):
    st.markdown(
        f"""
<div class="section-heading">
  <div>
    <div class="section-title">{html.escape(title)}</div>
    <div class="section-subtitle">{html.escape(subtitle)}</div>
  </div>
</div>
""",
        unsafe_allow_html=True
    )

def metric_card(icon, label, value, detail):
    st.markdown(
        f"""
<div class="metric-card">
  <div class="metric-icon">{icon}</div>
  <div class="metric-label">{html.escape(label)}</div>
  <div class="metric-value">{html.escape(str(value))}</div>
  <div class="metric-detail">{html.escape(detail)}</div>
</div>
""",
        unsafe_allow_html=True
    )

# ---------------------------------------------------------
# NAVIGATION / BRAND
# ---------------------------------------------------------

st.markdown("""
<div class="brand">
  <div class="brand-logo">✦</div>
  <div class="brand-text">Grade<span>Flow</span></div>
  <div class="brand-tag">● STUDENT INTELLIGENCE</div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# HERO
# ---------------------------------------------------------

st.markdown("""
<div class="hero">
  <div class="eyebrow">ACADEMIC PERFORMANCE PLATFORM</div>
  <h1>Every student.<br>
  <span class="gradient-text">Every achievement.</span></h1>
  <p>Manage student grades, track academic performance
  and uncover class insights — all in one beautifully
  simple workspace.</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# PERFORMANCE METRICS
# ---------------------------------------------------------

students = st.session_state.students
marks = [s["Mark"] for s in students]

average = sum(marks) / len(marks) if marks else None
highest = max(marks) if marks else None
lowest = min(marks) if marks else None

section(
    "Performance overview",
    "Your classroom at a glance"
)

c1, c2, c3, c4 = st.columns(4)

with c1:
    metric_card(
        "◈", "CLASS AVERAGE",
        f"{average:.1f}" if average is not None else "—",
        "Overall performance"
    )

with c2:
    metric_card(
        "↗", "HIGHEST SCORE",
        highest if highest is not None else "—",
        "Top achievement"
    )

with c3:
    metric_card(
        "↘", "LOWEST SCORE",
        lowest if lowest is not None else "—",
        "Lowest recorded mark"
    )

with c4:
    metric_card(
        "◎", "TOTAL STUDENTS",
        len(students),
        "Students enrolled"
    )

# ---------------------------------------------------------
# ADD STUDENT
# ---------------------------------------------------------

section(
    "Add a student",
    "Enter a name and a mark to update the dashboard"
)

with st.form("add_student", clear_on_submit=True):
    left, middle, right = st.columns([2.4, 1, 1.2])

    with left:
        name = st.text_input(
            "Student name",
            placeholder="Enter full name"
        )

    with middle:
        mark = st.number_input(
            "Mark (0–100)",
            min_value=0,
            max_value=100,
            value=75,
            step=1
        )

    with right:
        st.write("")
        st.write("")
        submitted = st.form_submit_button(
            "＋ Add Student",
            use_container_width=True
        )

    if submitted:
        clean_name = name.strip()

        if not clean_name:
            st.error("Please enter a student name.")
        else:
            st.session_state.students.append({
                "Name": clean_name,
                "Mark": int(mark),
                "Grade": get_grade(int(mark))
            })

            st.session_state.notice = (
                f"{clean_name} was added successfully."
            )
            st.rerun()

if st.session_state.notice:
    st.success(st.session_state.notice)
    st.session_state.notice = None

# ---------------------------------------------------------
# STUDENT RESULTS
# ---------------------------------------------------------

section(
    "Student directory",
    "Live grade records and individual results"
)

if students:
    search = st.text_input(
        "Search students",
        placeholder="Search by student name...",
        key="student_search"
    )

    filtered = [
        s for s in students
        if search.lower().strip() in s["Name"].lower()
    ]

    if filtered:
        df = pd.DataFrame(filtered)

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Name": st.column_config.TextColumn(
                    "Student name",
                    width="large"
                ),
                "Mark": st.column_config.ProgressColumn(
                    "Score / 100",
                    min_value=0,
                    max_value=100,
                    format="%d"
                ),
                "Grade": st.column_config.TextColumn(
                    "Grade",
                    width="small"
                )
            }
        )
    else:
        st.info("No students match your search.")

    st.caption(
        f"Showing {len(filtered)} of {len(students)} students"
    )

    col_download, col_clear = st.columns([3, 1])

    with col_download:
        export_df = pd.DataFrame(students)
        st.download_button(
            "↓ Export results as CSV",
            data=export_df.to_csv(index=False),
            file_name="gradeflow_results.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col_clear:
        with st.popover(
            "Clear all records",
            use_container_width=True
        ):
            st.warning(
                "This removes all students from this session."
            )
            if st.button(
                "Confirm clear",
                use_container_width=True
            ):
                st.session_state.students = []
                st.rerun()

else:
    st.markdown("""
<div class="empty-state">
  <div class="empty-icon">◎</div>
  <div class="empty-title">Your classroom awaits</div>
  <div class="empty-subtitle">
    Add your first student above to start building
    your performance dashboard.
  </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# CLASS GRADE DISTRIBUTION
# ---------------------------------------------------------

if students:
    section(
        "Grade distribution",
        "How students are performing across grade levels"
    )

    grades = ["A", "B", "C", "D", "F"]
    counts = {
        grade: sum(
            s["Grade"] == grade for s in students
        )
        for grade in grades
    }

    chips = "".join(
        f'<span class="grade-chip grade-{g}">'
        f'Grade {g} · {counts[g]}</span>'
        for g in grades
    )

    st.markdown(
        chips,
        unsafe_allow_html=True
    )

    chart_data = pd.DataFrame({
        "Grade": grades,
        "Students": [counts[g] for g in grades]
    }).set_index("Grade")

    st.bar_chart(
        chart_data,
        color="#897BFF"
    )

# ---------------------------------------------------------
# FOOTER
# ---------------------------------------------------------

st.markdown("""
<div class="footer">
  <span>© GradeFlow · Student Performance Dashboard</span>
  <span>Designed with care · Powered by Streamlit</span>
</div>
""", unsafe_allow_html=True)