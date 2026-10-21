// Header buttons like the prototype: "Clear chat" (trash) and "Ask a question".
// They replace Chainlit's pencil "New chat" button, which stays hidden but does the work.
//
// Chainlit's element ids (#new-chat-button, #chat-input, #header) are internal and can change
// in a new version (backlog #9). So every lookup has a fallback, the styles live here (no
// dependency on custom.css), and if the header can't be found the buttons float top-left.
(function () {
  const ICONS = {
    trash:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>',
    ask:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M12 7v6"/><path d="M9 10h6"/></svg>',
  };

  const STYLE = `
    #fl-header-actions { display: flex; align-items: center; gap: 8px; }
    #fl-header-actions.fl-floating { position: fixed; top: 12px; left: 12px; z-index: 50; }
    .fl-header-button {
      display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 12px;
      border: 1px solid hsl(var(--border, 240 4% 30%)); border-radius: 8px; background: transparent;
      color: hsl(var(--muted-foreground, 240 5% 65%)); font-size: 14px; font-weight: 500; cursor: pointer;
      transition: background-color 0.15s, color 0.15s;
    }
    .fl-header-button:hover {
      background: hsl(var(--accent, 240 4% 20%)); color: hsl(var(--foreground, 0 0% 98%));
    }
    .fl-header-button svg { width: 18px; height: 18px; flex-shrink: 0; }
  `;

  // Wait this long for Chainlit's header before showing the buttons floating instead
  const HEADER_WAIT_MS = 5000;
  const startedAt = Date.now();

  function findNewChatButton() {
    return (
      document.getElementById("new-chat-button") ||
      document.querySelector('[data-testid*="new-chat"], button[aria-label*="new chat" i], button[title*="new chat" i]')
    );
  }

  function findQuestionBox() {
    return (
      document.getElementById("chat-input") ||
      document.querySelector('#message-composer textarea, textarea[placeholder], textarea')
    );
  }

  function findHeader() {
    return document.getElementById("header") || document.querySelector("header");
  }

  function addStyle() {
    if (document.getElementById("fl-header-style")) return;
    const style = document.createElement("style");
    style.id = "fl-header-style";
    style.textContent = STYLE;
    document.head.appendChild(style);
  }

  function clearChat() {
    const newChat = findNewChatButton();
    if (newChat) {
      newChat.click(); // Chainlit asks for confirmation, then clears the conversation
    } else if (window.confirm("Clear the conversation?")) {
      window.location.reload(); // a fresh page is a new chat
    }
  }

  // Takes the user to the question box: cursor inside, and the box lights up for a moment
  function askQuestion() {
    const input = findQuestionBox();
    if (!input) return;
    const box = document.getElementById("message-composer") || input.closest("form") || input;
    box.scrollIntoView({ block: "center", behavior: "smooth" });
    input.focus();
    // Blue glow (FilingLens blue) so the user sees where to type
    box.style.transition = "box-shadow 0.3s";
    box.style.boxShadow = "0 0 0 3px rgba(37, 99, 235, 0.85)";
    clearTimeout(box._flGlow);
    box._flGlow = setTimeout(() => {
      box.style.boxShadow = "";
    }, 1500);
  }

  function makeButton(id, label, icon, onClick) {
    const button = document.createElement("button");
    button.id = id;
    button.type = "button";
    button.className = "fl-header-button";
    button.innerHTML = icon + "<span>" + label + "</span>";
    button.addEventListener("click", onClick);
    return button;
  }

  function addButtons() {
    addStyle();
    const newChat = findNewChatButton();
    if (newChat) newChat.style.display = "none"; // the pencil; our "Clear chat" replaces it

    const existing = document.getElementById("fl-header-actions");
    const header = findHeader();
    // Floating because the header was missing, and now it's there: move into it
    if (existing && existing.classList.contains("fl-floating") && (newChat || header)) existing.remove();
    else if (existing) return;

    const actions = document.createElement("div");
    actions.id = "fl-header-actions";
    actions.append(
      makeButton("fl-clear-chat", "Clear chat", ICONS.trash, clearChat),
      makeButton("fl-ask-question", "Ask a question", ICONS.ask, askQuestion)
    );

    if (newChat) {
      (newChat.parentElement || newChat).after(actions);
    } else if (header) {
      header.prepend(actions);
    } else if (Date.now() - startedAt > HEADER_WAIT_MS && document.body) {
      actions.classList.add("fl-floating");
      document.body.appendChild(actions);
    }
  }

  // Chainlit redraws the page (new chat, theme change), so add the buttons again when needed
  new MutationObserver(addButtons).observe(document.documentElement, { childList: true, subtree: true });
  setTimeout(addButtons, HEADER_WAIT_MS + 100); // the floating fallback, if nothing else changed
  addButtons();
})();

// The citations side panel opens only when the user clicks a citation.
// Chainlit 2.12 also opens it by itself every time an answer with citations arrives
// (display="side" elements), with no setting to turn that off: when the panel opens or
// changes without a recent click, close it with its own close button.
(function () {
  const CLICK_WINDOW_MS = 1000;
  let lastClick = 0;
  let shownTitle = null;

  document.addEventListener("pointerdown", () => {
    lastClick = Date.now();
  }, true);

    // Keyboard users open a citation with Enter or Space
  document.addEventListener("keydown", (event) => {
    // Typing in the question box doesn't count, only keys pressed on the page (e.g. on a citation)
    if (event.target.closest && event.target.closest("textarea, input")) return;
    if (event.key === "Enter" || event.key === " ") lastClick = Date.now();
  }, true);

  function closeIfNotClicked() {
    const title = document.getElementById("side-view-title");
    const text = title ? title.textContent : null;
    if (text === shownTitle) return;
    shownTitle = text;
    if (!title || Date.now() - lastClick < CLICK_WINDOW_MS) return;
    const close = title.querySelector("button");
    if (close) {
      close.click();
    } else {
      // Small screens show the panel as a sheet, which closes with Escape
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    }
  }

  new MutationObserver(closeIfNotClicked).observe(document.body, { childList: true, subtree: true, characterData: true });
})();

// Suggested questions (backlog #4): each one on its own line under the answer, like ChatGPT.
// Chainlit puts them in the same row as the copy icon, so the first one sat next to it.
// They are found by their icon (cl.Action icon="message-circle-question" in app.py), not by
// Chainlit's internal classes. Styles live here, like the header buttons, so a cached
// custom.css can't break them.
(function () {
  const SUGGESTION = 'svg[class*="message-circle-question"]';
  const STYLE = `
    div:has(> button > ${SUGGESTION}) {
      flex-direction: column; align-items: stretch; width: 100%;
    }
    div:has(> button > ${SUGGESTION}) > button:not(:has(> ${SUGGESTION})) {
      align-self: flex-start;  /* the copy icon stays alone, on the left */
    }
    button:has(> ${SUGGESTION}) {
      justify-content: flex-start; height: auto; min-height: 40px; padding: 8px 4px;
      border-radius: 0; border-top: 1px solid hsl(var(--border, 240 4% 30%));
      white-space: normal; text-align: left;
    }
    button:has(> ${SUGGESTION}):hover { background: transparent; color: hsl(var(--foreground, 0 0% 98%)); }
  `;
  function addStyle() {
    if (document.getElementById("fl-suggestions-style") || !document.head) return;
    const style = document.createElement("style");
    style.id = "fl-suggestions-style";
    style.textContent = STYLE;
    document.head.appendChild(style);
  }
  addStyle();
  document.addEventListener("DOMContentLoaded", addStyle);
})();
