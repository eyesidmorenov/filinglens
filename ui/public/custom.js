// Header buttons like the prototype: "Clear chat" (trash) and "Ask a question".
// They replace Chainlit's pencil "New chat" button, which stays hidden but does the work.
(function () {
  const ICONS = {
    trash:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>',
    ask:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M12 7v6"/><path d="M9 10h6"/></svg>',
  };

  function makeButton(id, label, icon, onClick) {
    const button = document.createElement("button");
    button.id = id;
    button.type = "button";
    button.className = "fl-header-button";
    button.innerHTML = icon + "<span>" + label + "</span>";
    button.addEventListener("click", onClick);
    return button;
  }

  function askQuestion() {
    const input = document.getElementById("chat-input");
    if (!input) return;
    const box = document.getElementById("message-composer") || input;
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

  function addButtons() {
    const newChat = document.getElementById("new-chat-button");
    if (!newChat || document.getElementById("fl-header-actions")) return;

    const actions = document.createElement("div");
    actions.id = "fl-header-actions";
    actions.append(
      // Same as Chainlit's "New chat": asks for confirmation, then clears the conversation
      makeButton("fl-clear-chat", "Clear chat", ICONS.trash, () => newChat.click()),
      // Takes the user to the question box: cursor inside, and the box lights up for a moment
      makeButton("fl-ask-question", "Ask a question", ICONS.ask, askQuestion)
    );
    (newChat.parentElement || newChat).after(actions);
  }

  // Chainlit redraws the header (new chat, theme change), so add the buttons again when needed
  new MutationObserver(addButtons).observe(document.body, { childList: true, subtree: true });
  addButtons();
})();
