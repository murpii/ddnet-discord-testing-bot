from extensions.map_testing.categories import category_registry
from extensions.map_testing.commands import TestingCommands
from extensions.map_testing.listener import TestingListener
from extensions.map_testing.services.checker import MapChecker
from extensions.map_testing.views.approval import (
    ChannelUploadApproval,
    DebugReport,
    SubmitBuggyApproval,
    SubmitCleanApproval,
    ViewTestingChannelButton,
)
from extensions.map_testing.mapdiff import VisualDiffButton, SideBySideDiffButton
from extensions.map_testing.housekeeping import TestingHousekeeper
from extensions.map_testing.views.inactivity import StillInterestedButton, ArchiveRequestButton
from extensions.map_testing.views.add_coauthor import AddCoAuthorView
from extensions.map_testing.views.checklist import ChecklistView
from extensions.map_testing.views.testing_menu import TestingMenu


async def setup(bot):
    MapChecker.enabled = bot.map_checks_enabled
    category_registry.configure(bot.config)
    await bot.add_cog(TestingListener(bot))
    await bot.add_cog(TestingCommands(bot))
    await bot.add_cog(TestingHousekeeper(bot))
    # persistent views
    bot.add_view(TestingMenu(bot))
    bot.add_view(ChecklistView())
    bot.add_view(SubmitCleanApproval(bot))
    bot.add_view(SubmitBuggyApproval(bot))
    bot.add_view(ChannelUploadApproval(bot))
    bot.add_view(DebugReport(bot))
    bot.add_view(AddCoAuthorView())
    bot.add_dynamic_items(
        VisualDiffButton,
        SideBySideDiffButton,
        ViewTestingChannelButton,
        StillInterestedButton,
        ArchiveRequestButton,
    )
