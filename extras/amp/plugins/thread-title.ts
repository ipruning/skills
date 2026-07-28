import type { PluginAPI, Subscription, ThreadID } from "@ampcode/plugin";

export default function (amp: PluginAPI) {
    const experimental = amp.experimental;
    if (!experimental) {
        amp.logger.log(
            "Thread title status requires Amp experimental plugin APIs.",
        );
        return;
    }

    const statusItem = experimental.createStatusItem();
    let titleSubscription: Subscription | undefined;
    let activeThreadVersion = 0;

    async function showThread(activeThread: { id: ThreadID } | null) {
        titleSubscription?.unsubscribe();
        titleSubscription = undefined;
        const version = ++activeThreadVersion;

        if (!activeThread) {
            statusItem.update({ text: "Thread: —" });
            return;
        }

        const thread = amp.threads.get(activeThread.id);
        let titleWasEmitted = false;
        const updateTitle = (title: string | null) => {
            if (version !== activeThreadVersion) return;

            titleWasEmitted = true;
            statusItem.update({ text: `Thread: ${title ?? "Untitled"}` });
        };

        titleSubscription = thread.title.subscribe(updateTitle);
        const title = await thread.title.get();
        if (!titleWasEmitted) updateTitle(title);
    }

    amp.activeThread.subscribe((activeThread) => {
        void showThread(activeThread).catch((error) => {
            amp.logger.log("Failed to show the active thread title.", error);
        });
    });

    void showThread(amp.activeThread.current).catch((error) => {
        amp.logger.log("Failed to show the active thread title.", error);
    });
}
