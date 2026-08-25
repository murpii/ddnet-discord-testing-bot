import logging

log = logging.getLogger("mt")


class ErrorReporter:
    async def on_error(self, interaction, error, item):
        log.error("Unhandled error in %s", type(self).__name__, exc_info=error)
        handler = interaction.client.get_cog("ErrorHandler")
        if handler is None:
            return
        try:
            await handler.report_interaction_error(
                interaction, error, note=f"View error in `{type(self).__name__}`"
            )
        except Exception:
            log.exception("Failed to report the view error to the DBG channel")
