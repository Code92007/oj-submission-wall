(() => {
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get("token") || "";
  const action = params.get("action");
  // Keep the secret in memory, out of URLs, referrers, storage and access logs.
  history.replaceState(null, "", location.pathname);
  const title = document.querySelector("#recoveryTitle");
  const message = document.querySelector("#recoveryMessage");
  const form = document.querySelector("#resetForm");
  const verify = document.querySelector("#verifyEmailBtn");
  if (!/^[A-Za-z0-9_-]{43}$/.test(token) || !["verify-email", "reset-password"].includes(action)) {
    message.textContent = "链接无效，请从邮件中重新打开完整链接，或重新申请。";
    return;
  }
  title.textContent = action === "verify-email" ? "验证邮箱" : "重置密码";
  message.textContent = action === "verify-email"
    ? "确认后，此邮箱将用于找回 OJ 训练墙账号密码。"
    : "请设置至少 8 位的新密码。修改后，所有旧登录都会退出。";
  (action === "verify-email" ? verify : form).classList.remove("hidden");

  async function submit(button, password) {
    button.disabled = true;
    try {
      const response = await fetch(`/api/auth/${action}`, {
        method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({token, password}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "操作失败，请稍后重试");
      message.textContent = data.message;
      form.reset();
      form.classList.add("hidden");
      verify.classList.add("hidden");
    } catch (error) {
      message.textContent = error.message;
      button.disabled = false;
    }
  }
  verify.addEventListener("click", () => submit(verify));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (form.elements.password.value !== form.elements.confirmation.value) {
      message.textContent = "两次输入的密码不一致。";
      return;
    }
    submit(form.querySelector("button"), form.elements.password.value);
  });
})();
