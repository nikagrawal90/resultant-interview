# Development Steps

We will work through the assignment in the following order:

1. **Define the core algorithm**
   - Discuss and agree on the essential reconciliation logic before considering architecture or implementation details.

2. **Expand the algorithm through edge cases**
   - Test the core reasoning against messy, ambiguous, conflicting, missing, and adversarial record combinations.
   - Refine the algorithm only where the edge cases demonstrate a need.

3. **Design the solution architecture**
   - Decide how the agreed algorithm will be divided into clear components.
   - Design both batch reconciliation and scalable, efficient incremental reconciliation.

4. **Implement the solution**
   - Build the agreed design in Python using FastAPI.
   - Keep all code in the current repository.

5. **Test the implementation**
   - Verify the core algorithm, important edge cases, grouping behavior, merged records, and confidence results.

6. **Write the final README**
   - Document setup and run instructions.
   - Explain the important decisions and trade-offs.
   - Include final notes, limitations, and where the solution breaks or could be improved.
