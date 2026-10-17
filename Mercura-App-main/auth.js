(function () {
  var KEY = "mercura_merchant";

  function merchant() {
    try {
      var saved = JSON.parse(localStorage.getItem(KEY) || "null");
      if (!saved || !saved.username) return null;
      return saved;
    } catch (e) {
      return null;
    }
  }

  function file() {
    return location.pathname.split("/").pop() || "index.html";
  }

  var nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
  var reload = nav ? nav.type === "reload" : performance.navigation && performance.navigation.type === 1;
  if (reload) sessionStorage.removeItem("mercura-entered");

  var user = merchant();
  var page = file();
  if (page === "login.html") return;
  if (sessionStorage.getItem("mercura-entered") !== "1" || !user) {
    document.documentElement.hidden = true;
    location.replace("login.html");
    return;
  }

  function paint() {
    var who = user.username;
    document.querySelectorAll("[data-merchant]").forEach(function (el) {
      var key = el.getAttribute("data-merchant");
      var value = key === "name" || key === "first" || key === "username" ? who : user[key];
      if (value) el.textContent = value;
    });
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    var node;
    while ((node = walker.nextNode())) {
      if (!node.parentNode || /^(SCRIPT|STYLE)$/.test(node.parentNode.tagName)) continue;
      if (node.nodeValue.indexOf("Rajesh") === -1) continue;
      node.nodeValue = node.nodeValue.replace(/Rajesh Sharma/g, who).replace(/Rajesh S\./g, who).replace(/\bRajesh\b/g, who);
    }
    var card = document.querySelector(".mx-merchant");
    if (!card) return;
    var name = card.querySelector("b");
    var shop = card.querySelector("span");
    if (name) name.textContent = who;
    if (shop) shop.textContent = user.shop || "";
  }

  window.MercuraAuth = {
    merchant: merchant,
    signOut: function () {
      localStorage.removeItem(KEY);
      sessionStorage.removeItem("mercura-session");
      sessionStorage.removeItem("mercura-entered");
      location.href = "login.html";
    }
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", paint);
  else paint();
})();
