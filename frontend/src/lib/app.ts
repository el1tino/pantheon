// Mirrors APP_NAME in backend/app/config.py. This is the only place the
// frontend names the product; import it instead of hard-coding the name.
export const APP_NAME = "Pantheon";

// Mirrors GROUP_NAME in backend/app/config.py: what the group of models is called on screen.
export const GROUP_NAME = "assembly";
/** "an assembly" / "a panel": the group name with its article. */
export const A_GROUP = `${/^[aeiou]/i.test(GROUP_NAME) ? "an" : "a"} ${GROUP_NAME}`;
const cap = (s: string) => s[0].toUpperCase() + s.slice(1);
export const THE_GROUP = `the ${GROUP_NAME}`;
export const CAP_A_GROUP = cap(A_GROUP);
