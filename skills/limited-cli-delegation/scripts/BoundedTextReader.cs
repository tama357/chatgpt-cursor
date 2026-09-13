using System;
using System.IO;
using System.Text;
using System.Threading.Tasks;

public sealed class CliTextResult
{
    public string Text { get; set; }
    public bool ExceededLimit { get; set; }
}

public static class CliBoundedTextReader
{
    // Keep draining both pipes, but retain at most limit characters in memory.
    public static async Task<CliTextResult> ReadAsync(StreamReader reader, int limit)
    {
        var text = new StringBuilder();
        var buffer = new char[4096];
        bool exceeded = false;
        int count;
        while ((count = await reader.ReadAsync(buffer, 0, buffer.Length).ConfigureAwait(false)) > 0)
        {
            int remaining = limit - text.Length;
            if (count > remaining) exceeded = true;
            if (remaining > 0) text.Append(buffer, 0, Math.Min(count, remaining));
        }
        return new CliTextResult { Text = text.ToString(), ExceededLimit = exceeded };
    }
}
