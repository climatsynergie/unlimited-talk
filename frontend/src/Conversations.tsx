import { useEffect } from "react";
import { CallHistory } from "./CallHistory";
import { usePhone } from "./Phone";

export function Conversations({ admin }: { admin: boolean }) {
  const { controller, state, busy } = usePhone();
  useEffect(() => {
    void controller.refresh();
  }, [controller]);
  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>Conversations</h1>
          <p>Retrouvez vos contacts, vos appels et vos enregistrements.</p>
        </div>
      </div>
      <CallHistory
        admin={admin}
        disabled={
          !state.loaded ||
          busy ||
          state.automaticRunning ||
          state.automatic?.mode === "booking"
        }
      />
    </section>
  );
}
