/*
 * VoltCart chat widget. Add one line to any page:
 *
 *   <script src="https://help.voltcart.example/widget.js" async></script>
 *
 * It draws a chat button in the corner; clicking it opens our chat in an iframe.
 * - The iframe keeps both sides safe: the host page's CSS and scripts can't reach into the chat,
 *   and the chat talks to the API from our own origin (so CORS stays strict).
 * - The button lives in a Shadow DOM, so the host page's CSS can't restyle it (and ours can't
 *   leak into the page).
 * - The iframe loads only when first opened: the host page isn't slowed down.
 */
(function () {
  if (window.__voltcartWidget) return; // the script was included twice
  window.__voltcartWidget = true;

  var script = document.currentScript;
  var origin = new URL(script.src).origin; // where the chat lives
  var INK = "#1b1a17";
  var VOLT = "#d6f25a";

  var host = document.createElement("div");
  host.id = "voltcart-widget";
  var root = host.attachShadow({ mode: "open" });

  root.innerHTML =
    "<style>" +
    ":host{all:initial}" +
    ".launcher{position:fixed;right:24px;bottom:24px;z-index:2147483646;width:56px;height:56px;" +
    "border:0;border-radius:50%;background:" + INK + ";color:" + VOLT + ";cursor:pointer;" +
    "display:flex;align-items:center;justify-content:center;" +
    "box-shadow:0 10px 30px -10px rgba(0,0,0,.45);transition:transform .18s cubic-bezier(.2,.7,.2,1)}" +
    ".launcher:hover{transform:scale(1.06)}" +
    ".launcher:focus-visible{outline:3px solid " + VOLT + ";outline-offset:3px}" +
    ".launcher svg{width:26px;height:26px}" +
    ".panel{position:fixed;right:24px;bottom:96px;z-index:2147483647;" +
    "width:min(400px,calc(100vw - 32px));height:min(640px,calc(100vh - 120px));" +
    "border-radius:20px;overflow:hidden;background:#f7f5f0;" +
    "box-shadow:0 24px 60px -20px rgba(0,0,0,.45),0 0 0 1px rgba(0,0,0,.06);" +
    "opacity:0;transform:translateY(8px) scale(.98);transform-origin:bottom right;" +
    "pointer-events:none;transition:opacity .2s ease-out,transform .22s cubic-bezier(.2,.7,.2,1)}" +
    ".panel.open{opacity:1;transform:none;pointer-events:auto}" +
    "iframe{width:100%;height:100%;border:0;display:block}" +
    "@media (max-width:480px){.panel{right:0;bottom:0;width:100vw;height:100dvh;border-radius:0}" +
    ".panel.open~.launcher{display:none}}" +
    "@media (prefers-reduced-motion:reduce){.launcher,.panel{transition:none}}" +
    "</style>" +
    '<div class="panel" role="dialog" aria-label="VoltCart Help"></div>' +
    '<button class="launcher" type="button" aria-label="Open VoltCart help" aria-expanded="false"></button>';

  var CHAT_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>';
  var CLOSE_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';

  var panel = root.querySelector(".panel");
  var launcher = root.querySelector(".launcher");
  launcher.innerHTML = CHAT_ICON;
  var isOpen = false;

  function setOpen(open) {
    isOpen = open;
    if (open && !panel.firstChild) {
      var frame = document.createElement("iframe");
      frame.src = origin + "/widget";
      frame.title = "VoltCart Help chat";
      frame.allow = "clipboard-write";
      panel.appendChild(frame);
    }
    panel.classList.toggle("open", open);
    launcher.innerHTML = open ? CLOSE_ICON : CHAT_ICON;
    launcher.setAttribute("aria-expanded", String(open));
    launcher.setAttribute("aria-label", open ? "Close VoltCart help" : "Open VoltCart help");
    if (open) setTimeout(function () { panel.firstChild && panel.firstChild.focus(); }, 50);
    else launcher.focus();
  }

  launcher.addEventListener("click", function () { setOpen(!isOpen); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && isOpen) setOpen(false);
  });
  // The chat's own close button. Only messages from our chat's origin are trusted
  window.addEventListener("message", function (e) {
    if (e.origin !== origin) return;
    if (e.data && e.data.type === "voltcart:close") setOpen(false);
  });

  function mount() { document.body.appendChild(host); }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
