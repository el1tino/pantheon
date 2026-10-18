const toast = document.getElementById("toast");
function say(text) {
  toast.textContent = text;
  toast.classList.add("on");
  setTimeout(() => toast.classList.remove("on"), 2200);
}
document.getElementById("year").textContent = new Date().getFullYear();
document.getElementById("cta").addEventListener("click", () => {
  document.getElementById("join").scrollIntoView({ behavior: "smooth" });
});
document.getElementById("signup").addEventListener("submit", (event) => {
  event.preventDefault();
  say("Thanks! You're on the list.");
  event.target.reset();
});
const observer = new IntersectionObserver((entries) => {
  entries.forEach((e) => { if (e.isIntersecting) e.target.classList.add("shown"); });
}, { threshold: 0.15 });
document.querySelectorAll(".reveal").forEach((el) => observer.observe(el));
