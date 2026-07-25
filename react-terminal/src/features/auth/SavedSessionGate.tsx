import { FormEvent, useState } from 'react';
import './SavedSessionGate.css';

interface SavedSessionGateProps {
  username: string;
  onContinue: (username: string) => void;
}

export function SavedSessionGate({ username, onContinue }: SavedSessionGateProps) {
  const [showAccountForm, setShowAccountForm] = useState(false);
  const [nextUsername, setNextUsername] = useState(username);

  const normalizedUsername = username.trim() || 'Efikemma';

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submittedUsername = nextUsername.trim();

    if (!submittedUsername) {
      return;
    }

    onContinue(submittedUsername);
  }

  return (
    <section className="session-gate">
      <div className="session-gate__hero">
        <span className="session-gate__eyebrow">Finwise Mobile</span>
        <h1>Welcome back</h1>
        <p>Your mobile trading workspace is ready. Jump back in with your saved session or switch accounts.</p>
      </div>

      <div className="glass-card session-gate__card">
        <div className="session-gate__status">Saved session found</div>
        <p className="session-gate__copy">
          Continue as <strong>{normalizedUsername}</strong> without entering your password again, or choose
          Login/Register to use another account.
        </p>

        <div className="session-gate__actions">
          <button className="session-gate__primary" type="button" onClick={() => onContinue(normalizedUsername)}>
            Continue as {normalizedUsername}
          </button>
          <button className="session-gate__secondary" type="button" onClick={() => setShowAccountForm((value) => !value)}>
            Login / Register
          </button>
        </div>

        {showAccountForm ? (
          <form className="session-gate__form" onSubmit={handleSubmit}>
            <label className="session-gate__field">
              <span>Username</span>
              <input
                type="text"
                value={nextUsername}
                onChange={(event) => setNextUsername(event.target.value)}
                placeholder="Enter your username"
                autoComplete="username"
              />
            </label>

            <button className="session-gate__primary session-gate__primary--compact" type="submit">
              Continue
            </button>
          </form>
        ) : null}
      </div>
    </section>
  );
}
