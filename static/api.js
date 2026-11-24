// 서버 API 호출 공통 함수: 결과를 { ok, status, data, message } 로 돌려준다
// body가 FormData(사진 업로드)면 그대로, 객체면 JSON으로 보낸다
async function apiRequest(method, url, body) {
  const headers = { "X-Requested-With": "fetch" };
  let payload;
  if (body instanceof FormData) {
    payload = body;  // 브라우저가 Content-Type을 알아서 붙인다
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  try {
    const response = await fetch(url, {
      method: method,
      headers: headers,
      body: payload,
      credentials: "same-origin",
    });
    let data = null;
    try {
      data = await response.json();
    } catch (e) {
      data = null;
    }
    if (response.ok) {
      return { ok: true, status: response.status, data: data, message: "" };
    }
    if (response.status === 401 && !url.startsWith("/api/auth/")) {
      window.location.href = "/login";  // 로그인이 풀리면 로그인 화면으로
    }
    const message = data && data.error ? data.error.message : "오류가 생겼어요. 잠시 후 다시 시도해 주세요.";
    return { ok: false, status: response.status, data: data, message: message };
  } catch (e) {
    return { ok: false, status: 0, data: null, message: "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요." };
  }
}

// 금액 표시: 350000 → "350,000원"
function won(n) {
  return Number(n || 0).toLocaleString("ko-KR") + "원";
}

// 로그아웃 버튼 (로그인한 화면에만 있음)
const logoutButton = document.getElementById("logout-btn");
if (logoutButton) {
  logoutButton.addEventListener("click", async () => {
    await apiRequest("POST", "/api/auth/logout");
    window.location.href = "/login";
  });
}
