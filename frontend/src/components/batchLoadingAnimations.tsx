import { useEffect, useState } from "react";

// CoffeeLoading — a cozy coffee cup with rising steam wisps

const coffeeStyles = `
  .coffee-scene {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1.5rem;
    user-select: none;
  }
  .coffee-cup {
    position: relative;
    width: 216px;
    height: 210px;
    image-rendering: pixelated;
  }
  .coffee-mug {
    position: absolute;
    bottom: 18px;
    left: 24px;
    width: 144px;
    height: 120px;
    background: #c4956a;
    border-radius: 0 0 24px 24px;
    border: 12px solid #8b5e3c;
    border-top: none;
    overflow: hidden;
  }
  .coffee-liquid {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 72px;
    background: linear-gradient(to bottom, #6b4423, #5c3317);
    border-radius: 0 0 12px 12px;
  }
  .coffee-liquid::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 12px;
    background: linear-gradient(to bottom, #d4b896, #a88b6a);
    border-radius: 6px;
  }
  .coffee-handle {
    position: absolute;
    bottom: 60px;
    left: 168px;
    width: 48px;
    height: 72px;
    border: 12px solid #8b5e3c;
    border-left: none;
    border-radius: 0 24px 24px 0;
  }
  .coffee-saucer {
    position: absolute;
    bottom: 0;
    left: 0;
    width: 192px;
    height: 24px;
    background: #d4a574;
    border-radius: 0 0 50% 50% / 0 0 100% 100%;
    border: 9px solid #8b5e3c;
    border-top: none;
  }
  .steam {
    position: absolute;
    top: 12px;
    width: 18px;
    height: 18px;
    background: rgba(180, 160, 140, 0.6);
    border-radius: 50%;
    animation: steamRise 4s ease-out infinite;
  }
  .steam:nth-child(1) { left: 54px; animation-delay: 0s; }
  .steam:nth-child(2) { left: 90px; animation-delay: 1.3s; }
  .steam:nth-child(3) { left: 126px; animation-delay: 2.6s; }
  @keyframes steamRise {
    0% {
      opacity: 0;
      transform: translateY(0) scale(1);
    }
    20% {
      opacity: 0.7;
    }
    100% {
      opacity: 0;
      transform: translateY(-60px) translateX(8px) scale(2);
    }
  }

  .coffee-msg {
    font-family: 'Courier New', monospace;
    font-size: 1.1rem;
    letter-spacing: 0.05em;
    color: var(--muted-foreground);
    min-height: 1.4em;
    transition: opacity 0.6s;
  }
`;

const COFFEE_MESSAGES = [
  "brewing your document...",
  "adding a splash of cream...",
  "stirring gently...",
  "sip and be patient...",
];

export function CoffeeLoading() {
  const [msgIdx, setMsgIdx] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setMsgIdx((i) => (i + 1) % COFFEE_MESSAGES.length), 8000);
    return () => clearInterval(id);
  }, []);

  return (
    <>
      <style>{coffeeStyles}</style>
      <div className="coffee-scene">
        <div className="coffee-cup">
          <div className="steam" />
          <div className="steam" />
          <div className="steam" />
          <div className="coffee-saucer" />
          <div className="coffee-mug">
            <div className="coffee-liquid" />
          </div>
          <div className="coffee-handle" />
        </div>
        <p className="coffee-msg">{COFFEE_MESSAGES[msgIdx]}</p>
      </div>
    </>
  );
}
