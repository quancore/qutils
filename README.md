# QUTILS
The Discord bot is designed for my Discord server called **Nightzone**. It includes several functionalities and modules can be considered unique.

# Modules
## Admin
- Setting and changing bot prefix
- Applying channel templates (channel permission template) to a text or voice channel by selecting from stored JSON templates
- Discard members by roles or intersection of roles
- Schedule new member removal event by using a role (whether the role is exist on the member or not). You can add exception members as well. This feature is useful to discard inactive members using an activity role.
- Listing members by role etc.
## General
- Showing a member profile that includes profile image, current status, how many days past since joined, how many days left to promote to new role etc.
- Provide some statistics like gender based (if the gender roles have been provided) ones
## Reminder
- Add, remove, list and delete reminder events for each member. The bot will remember you when the time is up
## Automation
- List and announce members that is not active in the server (there is a need for a role that states user activity. If this role is not given to a member, he/she is counting as inactive member. I am using **Statbot** in my server to assign an activity role) in announcement text channel
- Send private message to inactive members to participate back to servers
- Execute role upgrade events (I have a role hierarchy in my server so each member role is getting upgraded once the amount of time required to upgrade is up)
## Fun
- Various fun commands like displaying random cat, dog, duck; fetching the definition of a phrase from Urban dictionary; fetching the definition of a phrase from TDK (Turkish Language Foundation); rolling a dice; playing slot machine etc.
## Camdice
It is a special game for our server. Basically, all members connected to a voice channel are participating to a camdice game and each member is rolling a dice. N members with least dice values are lost the game and they are required to open their camera to finish the game.
## Talks
It is a module that helps to find a topic to talk in our server. Basically, it stores talk topics classified using different talk themes. All members can add new talk topics using predefined themes with additional explanation and links.
## Confession
This is another unique bot functionality. It enables members to share their confession anonymously, delete a confession already published, fetch the confession his/her published without exposing the identity (using private mesages). A moderator can warn or ban a member from confession module by using unique ban code shared with each confession so that the identity of a confession author is not exposing in any manner.
## TruthDare
The standart truth or dare game. It randomly select a pair of member to ask and answer a truth or dare question. There are a list of truth and dare questions/actions embedded to bot.