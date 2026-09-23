<script lang="ts">
import { onMount } from "svelte";
import { api } from "../api";

let status; // old game state to be managed
let existingGames; // populate this array with existing game names
let newGame = "";

const deleteGame = async (name) => {
    if (confirm(`Are you sure you want to delete the game '${name}'?`)) {
        await api.deleteGame(name);
        existingGames = existingGames.filter(g => g !== name);
    }
};

const createGame = async () => {
    if (newGame.trim()) {
        await api.createGame(newGame);
        existingGames.push(newGame);
        newGame = ""; // reset input
    }
};

onMount(async () => {
    const games = await api.games();
    existingGames = games.games;
});
</script>

<div class="panel">
    <header>
        <h2>Manage Your Games</h2>
    </header>
    <input bind:value={newGame} placeholder="New Game Name" />
    <button on:click={createGame}>Add Game</button>
    <ul>
        {#each existingGames as game}
            <li>
                {game} <button on:click={() => deleteGame(game)}>Delete</button>
            </li>
        {/each}
    </ul>
</div>
