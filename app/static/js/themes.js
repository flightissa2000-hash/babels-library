// The app's themes (Settings → Look): palettes for generated spines/covers, and reader colours for EPUBs.
window.THEMES = {
  wordtown: {
    name: "Word Town", inspired: "Noun Town",
    swatch: ["#bfe7ff", "#ff6b4a", "#ffc93c", "#8fd17a"],
    spines: ["#ff6b4a", "#ffc93c", "#4aa8ff", "#7ccf6b", "#b77cff", "#ff8fc0", "#3cc9b9"],
    reader: { bg: "#ffffff", ink: "#22304a", font: "'Nunito', sans-serif" },
    pageTint: "",
  },
  gruvbox: {
    name: "Gruvbox", inspired: "the Gruvbox colour scheme",
    swatch: ["#282828", "#ebdbb2", "#fe8019", "#fabd2f", "#b8bb26", "#83a598"],
    spines: ["#cc241d", "#98971a", "#d79921", "#458588", "#b16286", "#689d6a", "#d65d0e"],
    reader: { bg: "#282828", ink: "#ebdbb2", font: "'Nunito', sans-serif" },
    pageTint: "",
  },
  galaxy: {
    name: "Galaxy", inspired: "the night sky (Milky Way photo: ESO/S. Brunier)",
    swatch: ["#070a1c", "#9b8cff", "#ffd98a", "#8fb8ff", "#7fe0c8"],
    spines: ["#3b2f8f", "#5b3fb0", "#1f4f9a", "#2a6f8f", "#7a2f7a", "#9a6a20", "#2f3b7a"],
    reader: { bg: "#0b0f24", ink: "#e6ebff", font: "'Nunito', sans-serif" },
    pageTint: "",
  },
};
window.themeKey = (k) => (window.THEMES[k] ? k : "wordtown");
// set the saved theme before anything is drawn (the server's copy wins once settings load)
(() => { let k = null; try { k = localStorage.getItem("inkwell-theme"); } catch (e) {} document.documentElement.dataset.theme = window.themeKey(k); })();
